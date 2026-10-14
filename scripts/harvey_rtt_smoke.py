#!/usr/bin/env python3
"""Run one minimal real Harvey RTT trajectory before the full study."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.harvey_lab.artifacts import task_path, validate_task
from rubric_gen.benchmarks.harvey_lab.audits import (
    run_quality_audit,
    run_reward_hacking_audit,
)
from rubric_gen.benchmarks.harvey_lab.config import (
    HarveyExperiment,
    HarveyRun,
    load_experiment,
)
from rubric_gen.benchmarks.harvey_lab.controller import HarveyEvolutionController
from rubric_gen.benchmarks.harvey_lab.evaluator import HarveyEvaluator
from rubric_gen.benchmarks.harvey_lab.runtime import runtime_root_from_environment
from rubric_gen.benchmarks.harvey_lab.study import randomized_runs


def _smallest_task(experiment: HarveyExperiment, task_ids: tuple[str, ...]) -> str:
    def criterion_count(task_id: str) -> tuple[int, str]:
        path = task_path(experiment.benchmark.checkout / "tasks", task_id) / "task.json"
        task = validate_task(path)
        criteria = task.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError(f"Harvey smoke task has no criteria: {task_id}")
        return len(criteria), task_id

    return min(task_ids, key=criterion_count)


def smoke_run(experiment: HarveyExperiment, output_dir: Path) -> HarveyRun:
    """Build the smallest real run that exercises the changed RTT path."""
    source = next(
        run for run in randomized_runs(experiment) if run.condition == "red_team_trace"
    )
    benchmark = replace(
        experiment.benchmark,
        development_tasks=(
            _smallest_task(experiment, experiment.benchmark.development_tasks),
        ),
        selection_tasks=(
            _smallest_task(experiment, experiment.benchmark.selection_tasks),
        ),
        held_out_tasks=(
            _smallest_task(experiment, experiment.benchmark.held_out_tasks),
        ),
    )
    return replace(
        source,
        experiment_id=f"{experiment.experiment_id}-rtt-smoke",
        study_id=f"{experiment.experiment_id}-rtt-smoke",
        unit_id="rtt-smoke",
        replicate=1,
        output_dir=output_dir.resolve(),
        benchmark=benchmark,
        designer=replace(experiment.designer, rounds=1),
        outcome_replicates=1,
    )


def run_smoke(
    experiment: HarveyExperiment,
    *,
    output_dir: Path,
    resume: bool,
) -> int:
    run = smoke_run(experiment, output_dir)
    runtime_root = runtime_root_from_environment()
    evaluator = HarveyEvaluator(
        run,
        runtime_root=runtime_root,
        max_concurrency=1,
        max_retries=3,
    )
    child_resume = resume and (run.output_dir / "experiment.json").is_file()
    HarveyEvolutionController(
        run,
        runtime_root=runtime_root,
        evaluator=evaluator,
    ).run(resume=child_resume)
    if run_quality_audit(run, evaluator=evaluator):
        return 1
    judgments = run.output_dir / "audits" / "reward-hacking" / "judgments"
    detection_resume = judgments.is_dir() and any(judgments.iterdir())
    if run_reward_hacking_audit(
        run,
        resume=detection_resume,
        max_concurrency=1,
    ):
        return 1
    quality = run.output_dir / "audits" / "quality-transfer" / "summary.json"
    detection = judgments / "detection-rates.json"
    if not quality.is_file() or not detection.is_file():
        raise RuntimeError("Harvey RTT smoke lacks completed quality or RH audit")
    write_json_atomic(
        run.output_dir / "smoke-summary.json",
        {
            "kind": "harvey-rtt-real-smoke",
            "status": "completed",
            "source_experiment": experiment.experiment_id,
            "run": {
                "experiment_id": run.experiment_id,
                "condition": run.condition,
                "development_tasks": list(run.benchmark.development_tasks),
                "selection_tasks": list(run.benchmark.selection_tasks),
                "held_out_tasks": list(run.benchmark.held_out_tasks),
                "rounds": run.designer.rounds,
                "outcome_replicates": run.outcome_replicates,
                "audit_models": list(run.audit.models),
            },
            "quality_summary": json.loads(quality.read_text(encoding="utf-8")),
            "detection_rates": json.loads(detection.read_text(encoding="utf-8")),
        },
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    experiment = load_experiment(args.experiment)
    if os.path.lexists(args.output_dir) and not args.resume:
        raise FileExistsError(f"Harvey RTT smoke output already exists: {args.output_dir}")
    return run_smoke(
        experiment,
        output_dir=args.output_dir,
        resume=args.resume,
    )


if __name__ == "__main__":
    raise SystemExit(main())
