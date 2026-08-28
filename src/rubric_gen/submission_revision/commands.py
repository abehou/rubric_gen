"""Handlers for the submission-revision experiment DAG."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.seeds import (
    SeedSetConfig,
    SeedSetRunner,
)
from rubric_gen.submission_revision.paraphrases import (
    ParaphraseRunConfig,
    ParaphraseRunner,
)
from rubric_gen.submission_revision.study import (
    StudyRunConfig,
    StudyRunner,
    _exclusive_study_lease,
)
from rubric_gen.runtime.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.runtime.vllm import parse_vllm_endpoints


_RESTART_IDENTITY_FILES = {
    "revise": (
        "study.json",
        "rubric-gen-randomized-revision-study",
    ),
}


def run_seed(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    return SeedSetRunner(SeedSetConfig(
        experiment=experiment,
        output_dir=Path(str(experiment.dag["seed"]["output_dir"])),
        max_concurrency=args.max_concurrency,
        vllm_endpoints=endpoints,
    )).run()


def run_revise(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    return StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=Path(str(experiment.dag["seed"]["output_dir"])),
        paraphrase_run_dir=Path(
            str(experiment.dag["paraphrase"]["output_dir"])
        ),
        output_dir=Path(str(experiment.dag["revise"]["output_dir"])),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm_endpoints=endpoints,
    )).run()


def run_paraphrase(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    return ParaphraseRunner(ParaphraseRunConfig(
        experiment=experiment,
        output_dir=Path(str(experiment.dag["paraphrase"]["output_dir"])),
        max_concurrency=args.max_concurrency,
        vllm_endpoints=endpoints,
    )).run()


def run_detect(args: argparse.Namespace) -> int:
    from rubric_gen.submission_revision.direct_audit import (
        DirectAuditConfig,
        run_direct_audit,
    )
    from rubric_gen.submission_revision.rh_protocol import (
        EvaluationConfig,
    )
    from rubric_gen.submission_revision.rh_evaluation_targets import (
        load_evaluation_targets,
    )
    from rubric_gen.submission_revision.rh_evaluation_report import (
        write_reward_hacking_evaluation,
    )
    from rubric_gen.submission_revision.rh_outcome_panel import (
        HolisticPairwiseRunner,
        MechanisticEvaluationRunner,
    )

    experiment = load_experiment(resolve_project_path(args.experiment))
    study_dir = Path(str(experiment.dag["revise"]["output_dir"]))
    paraphrase_dir = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    output_dir = Path(str(experiment.dag["detect"]["output_dir"]))
    direct_dir = output_dir / "direct"
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    audit_models = tuple(
        str(model) for model in experiment.outcome_audit["models"]
    )
    direct_endpoints = {
        model: endpoints[model]
        for model in audit_models
        if model in endpoints
    }
    if direct_endpoints and len(direct_endpoints) != len(audit_models):
        missing = sorted(set(audit_models) - set(direct_endpoints))
        raise ValueError(
            "direct RH detection requires endpoints for all configured audit "
            f"models or none of them; missing={missing!r}"
        )

    mechanistic_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=paraphrase_dir,
        output_dir=output_dir / "mechanistic",
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm_endpoints=endpoints,
    )
    holistic_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=paraphrase_dir,
        output_dir=output_dir / "holistic",
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm_endpoints=endpoints,
    )
    targets = load_evaluation_targets(mechanistic_config)
    mechanistic_runner = MechanisticEvaluationRunner(
        mechanistic_config,
        targets,
    )
    holistic_runner = HolisticPairwiseRunner(
        holistic_config,
        targets,
    )

    # These reads prepare exact semantic jobs and enforce both stage caps.
    # They do not scan or hash complete revision workspaces.
    mechanistic_runner.preflight()
    holistic_runner.preflight()

    statuses: dict[str, int] = {}
    errors: list[tuple[str, Exception]] = []

    def execute(name: str, operation: Callable[[], int]) -> None:
        try:
            statuses[name] = int(operation())
        except Exception as exc:
            errors.append((name, exc))

    execute(
        "direct",
        lambda: run_direct_audit(DirectAuditConfig(
            study_dir=study_dir,
            output_dir=direct_dir,
            max_concurrency=args.max_concurrency,
            resume=args.resume,
            base_urls=direct_endpoints,
        )),
    )
    execute("mechanistic", mechanistic_runner.run)
    execute("holistic", holistic_runner.run)
    if not errors:
        write_reward_hacking_evaluation(output_dir)
    if errors:
        stages = ", ".join(name for name, _error in errors)
        first = errors[0][1]
        raise RuntimeError(
            f"RH detection suite failed in {stages}; other stages were still run"
        ) from first
    return int(any(statuses.values()))


def run_dag(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    resume = bool(getattr(args, "resume", False))
    restart = bool(getattr(args, "restart", False))
    vllm = getattr(args, "vllm", [])
    if resume and restart:
        raise ValueError("--resume and --restart are mutually exclusive")
    common = argparse.Namespace(
        experiment=str(experiment.path),
        max_concurrency=args.max_concurrency,
        resume=resume,
        vllm=vllm,
    )
    if run_seed(common):
        return 1
    if run_paraphrase(common):
        return 1
    if restart:
        _restart_experiment_outputs(experiment)
    if run_revise(common):
        return 1
    detect = argparse.Namespace(
        experiment=str(experiment.path),
        max_concurrency=args.max_concurrency,
        resume=resume,
        vllm=vllm,
    )
    return run_detect(detect)


def _restart_experiment_outputs(experiment: Experiment) -> None:
    roots = {
        stage: Path(str(experiment.dag[stage]["output_dir"])).resolve()
        for stage in ("revise", "detect")
    }
    _validate_restart_roots(experiment, roots)
    study_root = roots["revise"]
    if os.path.lexists(study_root):
        with _exclusive_study_lease(study_root):
            detached = _detach_restart_roots(roots)
    else:
        detached = _detach_restart_roots(roots)
    _remove_detached_roots(detached)

def _validate_restart_roots(
    experiment: Experiment,
    roots: dict[str, Path],
) -> None:
    forbidden = {
        Path(Path.cwd().anchor),
        Path.home().resolve(),
        PROJECT_ROOT.resolve(),
        experiment.path.parent.resolve(),
        experiment.tasks_dir.resolve(),
    }
    values = tuple(roots.values())
    if len(set(values)) != len(values):
        raise RuntimeError("restart output directories must be distinct")
    for stage, root in roots.items():
        expected_experiment_id = experiment.experiment_id
        if root in forbidden or root.name != expected_experiment_id:
            raise RuntimeError(
                f"unsafe {stage} restart output directory: {root}; "
                f"its final component must equal {expected_experiment_id}"
            )
        if any(
            root != other and _contains(root, other)
            for other in values
        ):
            raise RuntimeError("restart output directories must not overlap")
        if not os.path.lexists(root):
            continue
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(
                f"restart output is not a regular directory: {root}"
            )
        _validate_restart_identity(experiment, stage, root)


def _validate_restart_identity(
    experiment: Experiment,
    stage: str,
    root: Path,
) -> None:
    specification = _RESTART_IDENTITY_FILES.get(stage)
    if specification is None:
        return
    filename, expected_kind = specification
    identity_path = root / filename
    if not identity_path.exists():
        allowed = {".study.lock"} if stage == "revise" else set()
        if {path.name for path in root.iterdir()} - allowed:
            raise RuntimeError(
                f"restart refuses unowned {stage} output directory: {root}"
            )
        return
    if identity_path.is_symlink() or not identity_path.is_file():
        raise RuntimeError(f"invalid restart identity file: {identity_path}")
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid restart identity file: {identity_path}") from exc
    if (
        not isinstance(identity, dict)
        or identity.get("kind") != expected_kind
        or identity.get("experiment_id") != experiment.experiment_id
    ):
        raise RuntimeError(
            f"restart output identity does not match the experiment: {root}"
        )


def _detach_restart_roots(roots: dict[str, Path]) -> list[Path]:
    detached: list[tuple[Path, Path]] = []
    try:
        for stage in ("detect", "revise"):
            root = roots[stage]
            if not os.path.lexists(root):
                continue
            destination = root.with_name(
                f".{root.name}.restart-{secrets.token_hex(8)}"
            )
            os.replace(root, destination)
            detached.append((root, destination))
    except Exception:
        for original, destination in reversed(detached):
            if not os.path.lexists(original) and os.path.lexists(destination):
                os.replace(destination, original)
        raise
    return [destination for _, destination in detached]


def _remove_detached_roots(detached: list[Path]) -> None:
    for root in detached:
        try:
            _force_remove_directory(root)
        except (OSError, RuntimeError) as exc:
            print(
                f"warning: detached restart output remains at {root}: {exc}",
                file=sys.stderr,
            )


def _force_remove_directory(root: Path) -> None:
    root.chmod(stat.S_IMODE(os.lstat(root).st_mode) | stat.S_IRWXU)
    for current, directories, _ in os.walk(root, followlinks=False):
        current_path = Path(current)
        current_path.chmod(
            stat.S_IMODE(os.lstat(current_path).st_mode) | stat.S_IRWXU
        )
        for directory in directories:
            child = current_path / directory
            if not child.is_symlink():
                child.chmod(
                    stat.S_IMODE(os.lstat(child).st_mode) | stat.S_IRWXU
                )
    shutil.rmtree(root)
    if os.path.lexists(root):
        raise RuntimeError(f"failed to remove restart output directory: {root}")


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def run_judge(args: argparse.Namespace) -> int:
    from rubric_gen.submission_revision.original_rubric import (
        OriginalRubricEnsembleRunner,
    )
    from rubric_gen.submission_revision.original_rubric_inputs import (
        OriginalRubricEnsembleConfig,
    )

    return OriginalRubricEnsembleRunner(OriginalRubricEnsembleConfig(
        study_dir=resolve_project_path(args.study_dir),
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        resume=args.resume,
    )).run()
