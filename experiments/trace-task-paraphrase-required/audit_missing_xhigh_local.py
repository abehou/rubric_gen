"""Recover only terminal Luna-xhigh audit gaps with a larger output ceiling."""
from __future__ import annotations

import argparse
import copy
from contextlib import nullcontext
from dataclasses import replace
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from rubric_gen.runtime.audit_execution import AuditExecutor, audit_output_owner
from rubric_gen.runtime.capacity import policy, reservation
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation import jobs, score_execution
from rubric_gen.submission_revision.evaluation.direct import (
    DirectDetectionConfig,
    prepare_direct_detection,
)
from rubric_gen.submission_revision.evaluation.jobs import (
    EvaluationConfig,
    PreparedRubricFreeScores,
)
from rubric_gen.submission_revision.evaluation.runner import RubricFreeScoreRunner
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.source_resolution import (
    StudySources,
    resolve_study_sources,
)


ROOT = Path(__file__).resolve().parents[2]
MODEL = "gpt-5.6-luna"
RECOVERY_MAX_OUTPUT_TOKENS = 16_384


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _failed_keys(root: Path, instrument: str) -> set[str]:
    summary = _read(root / instrument / "summary.json")
    return {str(row["judgment_key"]) for row in summary["judge_failures"]}


def _prepare_free_recovery(
    experiment: Experiment,
    study_dir: Path,
    paraphrase_dir: Path,
    original_audit: Path,
    recovery_root: Path,
    concurrency: int,
) -> RubricFreeScoreRunner:
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=paraphrase_dir,
        output_dir=recovery_root,
        max_concurrency=concurrency,
        resume=True,
    )
    sources = resolve_study_sources(study_dir, experiment)
    runner = RubricFreeScoreRunner(config, load_evaluation_targets(config, sources))
    runner.preflight()
    prepared = runner._prepared
    if prepared is None:
        raise RuntimeError("rubric-free preflight produced no plan")
    absolute_failures = _failed_keys(original_audit, "absolute_score")
    pairwise_failures = _failed_keys(original_audit, "pairwise_preference")
    absolute = tuple(job for job in prepared.unique_absolute_jobs if job.key in absolute_failures)
    pairwise = tuple(job for job in prepared.unique_pairwise_jobs if job.key in pairwise_failures)
    if len(absolute) != 24 or len(pairwise) != 6:
        raise RuntimeError(
            f"unexpected original missing scope: absolute={len(absolute)}, pairwise={len(pairwise)}"
        )

    original_absolute = jobs._rubric_free_absolute_score_request
    original_pairwise = jobs._pairwise_preference_request

    def larger_absolute(job):
        return replace(
            original_absolute(job), max_output_tokens=RECOVERY_MAX_OUTPUT_TOKENS
        )

    def larger_pairwise(job):
        return replace(
            original_pairwise(job), max_output_tokens=RECOVERY_MAX_OUTPUT_TOKENS
        )

    # This is an explicitly recorded recovery request setting, not a rewrite of
    # the canonical 2,048-token judgments or their preserved attempt records.
    jobs._rubric_free_absolute_score_request = larger_absolute
    jobs._pairwise_preference_request = larger_pairwise
    score_execution._rubric_free_absolute_score_request = larger_absolute
    score_execution._pairwise_preference_request = larger_pairwise
    plan = runner._predispatch_plan(absolute, pairwise)
    runner._prepared = PreparedRubricFreeScores(
        targets=prepared.targets,
        models=prepared.models,
        implementation_identity=prepared.implementation_identity,
        pairwise_order_plan=prepared.pairwise_order_plan,
        absolute_jobs=absolute,
        pairwise_jobs=pairwise,
        unique_absolute_jobs=absolute,
        unique_pairwise_jobs=pairwise,
        predispatch_plan=plan,
    )
    return runner


def _recovery_experiment(experiment: Experiment) -> Experiment:
    payload = copy.deepcopy(experiment.payload)
    payload["outcome_audit"]["max_output_tokens"] = RECOVERY_MAX_OUTPUT_TOKENS
    return Experiment(experiment.path, payload)


def _direct_recoveries(
    experiment: Experiment,
    sources: StudySources,
    original_audit: Path,
    recovery_root: Path,
    concurrency: int,
):
    recovery_experiment = _recovery_experiment(experiment)
    for window in RevisionDetectionWindow:
        summaries = list(
            (original_audit / f"direct_{window.value}" / "evaluations").glob(
                "*/summary.json"
            )
        )
        if len(summaries) != 1:
            raise RuntimeError(f"expected one original direct summary for {window.value}")
        missing = {
            str(row["source_path"])
            for row in _read(summaries[0])["records"]
            if "verdict" not in row
        }
        if not missing:
            continue
        selected = tuple(
            source for source in sources.revisions if str(source.directory) in missing
        )
        if len(selected) != len(missing):
            raise RuntimeError(f"could not resolve every missing {window.value} source")
        filtered = StudySources(
            recovery_experiment, sources.root, sources.ledger, selected
        )
        runner = prepare_direct_detection(
            DirectDetectionConfig(
                experiment=recovery_experiment,
                study_dir=sources.root,
                output_dir=recovery_root / f"direct_{window.value}",
                max_concurrency=concurrency,
                resume=True,
                window=window,
            ),
            filtered,
            {},
        )
        yield window.value, runner


def _completed_free_subset(root: Path) -> bool:
    return (
        len(tuple((root / "absolute_score" / "records").glob("*.json"))) == 24
        and len(tuple((root / "pairwise_preference" / "records").glob("*.json"))) == 6
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--original-audit", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-concurrency", type=int, default=2)
    args = parser.parse_args()
    for path in (
        args.experiment,
        args.runtime_config,
        args.path_map,
        args.original_audit,
    ):
        if not path.is_absolute() or path.is_symlink() or not path.exists():
            raise RuntimeError(f"recovery input must be absolute and non-symlinked: {path}")
    if not args.output_root.is_absolute() or args.output_root.is_symlink():
        raise RuntimeError("recovery output must be absolute and non-symlinked")
    if not 1 <= args.max_concurrency <= 2:
        raise ValueError("recovery concurrency must be one or two")

    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(args.path_map)
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(args.runtime_config)
    os.environ["RUBRIC_GEN_OPENAI_REASONING_EFFORT"] = "xhigh"
    if policy()["audit_studies"] != 1:
        raise RuntimeError("local audit studies must remain serialized")
    credentials = dotenv_values(ROOT / ".env.local")
    key = os.environ.get("OPENAI_API_KEY") or credentials.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("configured OPENAI_API_KEY absent")
    os.environ["OPENAI_API_KEY"] = str(key)

    experiment = load_experiment(args.experiment)
    study_dir = Path(str(experiment.dag["revise"]["output_dir"]))
    paraphrase_dir = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    sources = resolve_study_sources(study_dir, experiment)
    free = None
    if not _completed_free_subset(args.output_root):
        free = _prepare_free_recovery(
            experiment,
            study_dir,
            paraphrase_dir,
            args.original_audit,
            args.output_root,
            args.max_concurrency,
        )
    direct = tuple(
        _direct_recoveries(
            experiment,
            sources,
            args.original_audit,
            args.output_root,
            args.max_concurrency,
        )
    )
    reused = True if free is None else free.prepare_resume()
    reused = all(runner.prepare_resume() for _, runner in direct) and reused
    admission = nullcontext() if reused else reservation("audit")
    with audit_output_owner(args.output_root), admission, AuditExecutor(
        args.max_concurrency, (MODEL,)
    ) as requests:
        free_status = 0
        if free is not None:
            try:
                free_status = free.run_prepared(executor=requests)
            except KeyError:
                # The canonical summarizer requires all 45 rubric-free jobs in
                # one output root. Recovery deliberately contains only the 30
                # missing jobs, retained for merged terminal reporting.
                if not _completed_free_subset(args.output_root):
                    raise
                free_status = 0
        direct_status = {
            window: runner.run_prepared(executor=requests)
            for window, runner in direct
        }
    if free_status or any(direct_status.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
