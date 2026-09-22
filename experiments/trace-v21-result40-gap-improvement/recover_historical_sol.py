"""Recover only missing Sol jobs in a partial historical Sol+Gemini audit."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import AuditExecutor, audit_output_owner
from rubric_gen.runtime.capacity import policy, reservation
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.direct import (
    DirectDetectionConfig,
    prepare_direct_detection,
)
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import (
    RubricFreeScoreRunner,
    RubricScoreRunner,
)
from rubric_gen.submission_revision.evaluation.targets import (
    load_evaluation_targets,
)
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import (
    resolve_study_sources,
)

from audit_inventory import model_coverage, saved_model_counts
from audit_sol_opus import clean_commit, validate_revision, validate_runtime
from make_configs import (
    PANEL as HISTORICAL_PANEL,
    ROOT,
    RUN,
    SMOKE_TASK,
    TASKS,
    config_path,
)


SOL = "gpt-5.6-sol"
MAX_CONCURRENCY = 60


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_error(error: BaseException) -> str:
    value = str(error).replace("\n", " ")
    value = re.sub(
        r"(?i)(authorization|bearer|api[_-]?key|token)(\s*[:=]?\s*)\S+",
        r"\1\2<redacted>",
        value,
    )
    return value[:500]


def credentials() -> None:
    value = os.environ.get("OPENAI_API_KEY") or dotenv_values(
        "/home/aydanh/repos/rubric_gen/.env.local"
    ).get("OPENAI_API_KEY")
    if not value:
        raise RuntimeError("configured credential unavailable: OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = str(value)


def _record_exists(root: Path, stage: str, key: str) -> bool:
    return (root / stage / "records" / f"{key}.json").is_file()


def _prepared_runners(task: str, workers: int):
    experiment = load_experiment(config_path(task))
    if tuple(experiment.outcome_audit["models"]) != HISTORICAL_PANEL:
        raise RuntimeError("historical audit execution panel changed")
    study = Path(experiment.dag["revise"]["output_dir"])
    paraphrases = Path(experiment.dag["paraphrase"]["output_dir"])
    audit = Path(experiment.dag["detect"]["output_dir"])
    sources = resolve_study_sources(study, experiment)
    rubric_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study,
        paraphrase_dir=paraphrases,
        output_dir=audit / "rubric_score",
        max_concurrency=workers,
        resume=True,
    )
    free_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study,
        paraphrase_dir=paraphrases,
        output_dir=audit,
        max_concurrency=workers,
        resume=True,
    )
    targets = load_evaluation_targets(rubric_config, sources)
    rubric = RubricScoreRunner(rubric_config, targets)
    free = RubricFreeScoreRunner(free_config, targets)
    rubric.preflight()
    free.preflight()
    shared_inputs: dict[object, object] = {}
    direct = {
        window.value: prepare_direct_detection(
            DirectDetectionConfig(
                experiment=experiment,
                study_dir=study,
                output_dir=audit / f"direct_{window.value}",
                max_concurrency=workers,
                resume=True,
                window=window,
            ),
            sources,
            shared_inputs,
        )
        for window in RevisionDetectionWindow
    }
    for runner in direct.values():
        runner.prepare_resume()
    return experiment, audit, rubric, free, direct


def missing_plan(task: str, workers: int) -> tuple[Path, list[dict[str, object]]]:
    _experiment, audit, rubric, free, direct = _prepared_runners(task, workers)
    plan: list[dict[str, object]] = []
    prepared_rubric = rubric._prepared
    prepared_free = free._prepared
    if prepared_rubric is None or prepared_free is None:
        raise RuntimeError("historical Sol recovery produced no accepted plan")
    for job in prepared_rubric.unique_jobs:
        if job.model == SOL and not _record_exists(audit, "rubric_score", job.key):
            plan.append({"stage": "rubric_score", "key": job.key, "runner": rubric, "job": job})
    for stage, jobs in (
        ("absolute_score", prepared_free.unique_absolute_jobs),
        ("pairwise_preference", prepared_free.unique_pairwise_jobs),
    ):
        for job in jobs:
            if job.model == SOL and not _record_exists(audit, stage, job.key):
                plan.append({"stage": stage, "key": job.key, "runner": free, "job": job})
    for window, runner in direct.items():
        standard = runner._standard_runner()
        for case in runner.config.source.cases:
            path = (
                runner.config.output_dir
                / "cases"
                / case.case_id
                / SOL
                / "score.json"
            )
            if path.is_file():
                continue
            job = runner._prepare_source_job(case, SOL)
            plan.append({
                "stage": f"direct_{window}",
                "key": case.case_id,
                "runner": standard,
                "job": job,
            })
    return audit, plan


def _execute(item: dict[str, object]):
    stage = str(item["stage"])
    runner = item["runner"]
    job = item["job"]
    if stage == "rubric_score":
        return runner._run_job(job)
    if stage == "absolute_score":
        return runner._run_absolute_job(job)
    if stage == "pairwise_preference":
        return runner._run_pairwise_job(job)
    if stage.startswith("direct_"):
        return runner.execute(job)
    raise RuntimeError(f"unknown historical Sol recovery stage: {stage}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--max-concurrency", type=int, default=MAX_CONCURRENCY)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("historical Sol recovery must run through Slurm")
    if args.task == SMOKE_TASK:
        raise RuntimeError("historical smoke-task Sol coverage is already complete")
    if not 1 <= args.max_concurrency <= MAX_CONCURRENCY:
        raise ValueError("Sol recovery concurrency must be between 1 and 60")
    commit = clean_commit()
    runtime = validate_runtime()
    validate_revision(args.task)
    audit, plan = missing_plan(args.task, args.max_concurrency)
    before = model_coverage(saved_model_counts(audit), SOL)
    if int(before["missing"]) != len(plan):
        raise RuntimeError(
            "native missing Sol plan differs from published-record inventory"
        )
    if not plan:
        print(json.dumps({"task_id": args.task, "missing": 0}), flush=True)
        return
    credentials()
    owner = (
        RUN
        / "owners"
        / f"recover-sol-{args.task}-{os.environ['SLURM_JOB_ID']}-"
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    owner.mkdir(parents=True, exist_ok=False)
    launch = {
        "kind": "result40-gap-historical-sol-missing-only-v1",
        "source_commit": commit,
        "config_sha256": sha256_file(config_path(args.task)),
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "task_id": args.task,
        "model": SOL,
        "historical_panel": list(HISTORICAL_PANEL),
        "gemini_dispatches": 0,
        "saved_before": int(before["saved"]),
        "missing_before": len(plan),
        "missing_by_stage": dict(Counter(str(item["stage"]) for item in plan)),
        "max_concurrency": args.max_concurrency,
        "runtime": runtime,
        "started_at": now(),
    }
    write_json_atomic(owner / "launch.json", launch)
    successes: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    with audit_output_owner(audit), reservation("audit"), AuditExecutor(
        args.max_concurrency, (SOL,)
    ) as executor:
        futures = {
            executor.submit(_execute, item, model=SOL): item for item in plan
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                if isinstance(result, dict) and result.get("status") == "failed":
                    failures.append({
                        "stage": item["stage"],
                        "key": item["key"],
                        "error_type": str(result.get("error_type", "unknown")),
                        "error": _safe_error(
                            RuntimeError(str(result.get("error", "unknown")))
                        ),
                    })
                else:
                    successes.append({"stage": item["stage"], "key": item["key"]})
            except Exception as error:
                failures.append({
                    "stage": item["stage"],
                    "key": item["key"],
                    "error_type": type(error).__name__,
                    "error": _safe_error(error),
                })
    after = model_coverage(saved_model_counts(audit), SOL)
    receipt = {
        **launch,
        "successful": len(successes),
        "failed": len(failures),
        "failures": sorted(failures, key=lambda row: (str(row["stage"]), str(row["key"]))),
        "saved_after": int(after["saved"]),
        "missing_after": int(after["missing"]),
        "finished_at": now(),
    }
    write_json_atomic(owner / "completed.json", receipt)
    status = RUN / "audit-sol-recovery-status"
    status.mkdir(parents=True, exist_ok=True)
    write_json_atomic(status / f"{args.task}.json", receipt)
    print(json.dumps(receipt), flush=True)
    if failures or int(after["missing"]):
        raise RuntimeError("historical Sol recovery incomplete; saved work retained")


if __name__ == "__main__":
    main()
