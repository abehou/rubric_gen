"""Handlers for the submission-revision experiment DAG."""

from __future__ import annotations

from rubric_gen.runtime.capacity import limited

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


_RESTART_IDENTITY_FILES = {
    "revise": (
        "study.json",
        "rubric-gen-randomized-revision-study",
    ),
}


def run_seed(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    return SeedSetRunner(SeedSetConfig(
        experiment=experiment,
        output_dir=Path(str(experiment.dag["seed"]["output_dir"])),
        max_concurrency=args.max_concurrency,
    )).run()


def run_revise(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    assignment_workers = getattr(args, "assignment_workers", None)
    return StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=Path(str(experiment.dag["seed"]["output_dir"])),
        paraphrase_run_dir=Path(
            str(experiment.dag["paraphrase"]["output_dir"])
        ),
        output_dir=Path(str(experiment.dag["revise"]["output_dir"])),
        max_concurrency=args.max_concurrency if assignment_workers is None else assignment_workers,
        resume=args.resume,
    )).run()


def run_paraphrase(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    return ParaphraseRunner(ParaphraseRunConfig(
        experiment=experiment,
        output_dir=Path(str(experiment.dag["paraphrase"]["output_dir"])),
        max_concurrency=args.max_concurrency,
    )).run()


def run_detect(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    study_value = getattr(args, "study_dir", None)
    study_dir = (
        resolve_project_path(study_value)
        if study_value is not None
        else Path(str(experiment.dag["revise"]["output_dir"]))
    )
    paraphrase_dir = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    output_dir = Path(str(experiment.dag["detect"]["output_dir"]))
    from rubric_gen.runtime.audit_execution import audit_owner
    with audit_owner(output_dir):
        return _run_detect_owned(args, experiment, study_dir, paraphrase_dir, output_dir)


def _run_detect_owned(args, experiment, study_dir, paraphrase_dir, output_dir) -> int:
    import time
    from rubric_gen.runtime.capacity import emit
    from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
    from rubric_gen.runtime.audit_execution import AuditExecutor
    from rubric_gen.submission_revision.source_resolution import resolve_study_sources
    from rubric_gen.submission_revision.evaluation.direct import DirectDetectionConfig, prepare_direct_detection
    from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
    from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
    from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
    from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner, RubricFreeScoreRunner
    rubric_score_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=paraphrase_dir,
        output_dir=output_dir / "rubric_score",
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )
    rubric_free_score_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=paraphrase_dir,
        output_dir=output_dir,
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )
    started = time.monotonic()
    emit('audit_phase', phase='source_scope_identity', output_dir=str(output_dir))
    sources = resolve_study_sources(study_dir, experiment)
    targets = load_evaluation_targets(rubric_score_config, sources)
    shared_evidence = {}
    direct_runners = {
        f"direct_{window.value}": prepare_direct_detection(DirectDetectionConfig(
            experiment=experiment, study_dir=study_dir,
            output_dir=output_dir / f"direct_{window.value}",
            max_concurrency=args.max_concurrency, resume=args.resume, window=window,
        ), sources, shared_evidence)
        for window in RevisionDetectionWindow
    }
    rubric_score_runner = RubricScoreRunner(
        rubric_score_config,
        targets,
    )
    rubric_free_score_runner = RubricFreeScoreRunner(
        rubric_free_score_config,
        targets,
    )

    # These reads prepare exact semantic jobs and enforce both stage caps.
    # They do not scan or hash complete revision workspaces.
    emit('audit_phase', phase='scoring_preparation', source_scope_seconds=time.monotonic()-started)
    rubric_score_runner.preflight()
    rubric_free_score_runner.preflight()
    emit('audit_phase', phase='saved_response_validation')
    rubric_score_runner.prepare_resume()
    rubric_free_score_runner.prepare_resume()

    statuses: dict[str, int] = {}
    errors: list[tuple[str, Exception]] = []
    stages = {**direct_runners, "rubric_score": rubric_score_runner,
              "rubric_free_score": rubric_free_score_runner}
    emit('audit_phase', phase='execution', preparation_seconds=time.monotonic()-started)
    def execute_stage(name, runner, requests):
        stage_started = time.monotonic()
        emit('audit_stage_started', stage=name)
        try:
            result = runner.run_prepared(executor=requests)
        except Exception as error:
            from rubric_gen.runtime.failures import failure_category
            emit('audit_stage_failed', stage=name, error_type=type(error).__name__,
                 category=failure_category(error), elapsed_seconds=time.monotonic()-stage_started)
            raise
        emit('audit_stage_completed', stage=name, exit_code=int(result),
             elapsed_seconds=time.monotonic()-stage_started)
        return result
    with AuditExecutor(args.max_concurrency, tuple(experiment.outcome_audit['models'])) as requests:
        with ThreadPoolExecutor(max_workers=len(stages)) as coordinators:
            futures = {coordinators.submit(execute_stage, name, runner, requests): name
                       for name, runner in stages.items()}
            while futures:
                done, _ = wait(futures, timeout=30, return_when=FIRST_COMPLETED)
                emit('audit_queue', **requests.status())
                for future in done:
                    name = futures.pop(future)
                    try:
                        statuses[name] = int(future.result())
                    except Exception as exc:
                        errors.append((name, exc))
                        print(f"{name}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
    if errors:
        raise ExceptionGroup("evaluation suite stage failures", [
            RuntimeError(f"{name}: {type(error).__name__}: {error}").with_traceback(error.__traceback__)
            for name, error in errors
        ])
    return int(any(statuses.values()))


def run_dag(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    resume = bool(getattr(args, "resume", False))
    restart = bool(getattr(args, "restart", False))
    if resume and restart:
        raise ValueError("--resume and --restart are mutually exclusive")
    common = argparse.Namespace(
        experiment=str(experiment.path),
        max_concurrency=args.max_concurrency,
        resume=resume,
        assignment_workers=getattr(args, "assignment_workers", None),
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
        study_dir=str(experiment.dag["revise"]["output_dir"]),
        max_concurrency=args.max_concurrency,
        resume=resume,
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
        resume=args.resume,
    )).run()
