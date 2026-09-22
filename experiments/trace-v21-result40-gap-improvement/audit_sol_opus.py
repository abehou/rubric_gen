"""Run one missing-only Result40 gap-pilot audit provider/task shard."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.runtime.audit_execution import audit_output_owner
from rubric_gen.submission_revision.commands import _run_detect_owned
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment

from make_configs import (
    PANEL as HISTORICAL_PANEL,
    ROOT,
    RUN,
    SMOKE_TASK,
    TASKS,
    config_path,
)


PROVIDERS = {
    "sol": ("gpt-5.6-sol", "OPENAI_API_KEY"),
    "opus": ("claude-opus-5", "ANTHROPIC_API_KEY"),
}
RUNTIME_PROVIDERS = {"sol": "openai", "opus": "anthropic"}
MAX_CONCURRENCY = 60
EXPECTED_WALL_TIME_MINUTES = 90


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_commit() -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if dirty.strip():
        raise RuntimeError("Sol+Opus audit source must be a clean commit")
    return commit


def planned_scopes() -> tuple[tuple[str, str], ...]:
    return tuple(
        (task, provider)
        for task in TASKS
        for provider in PROVIDERS
        if not (task == SMOKE_TASK and provider == "sol")
    )


def audit_dir(task: str, provider: str, experiment_id: str) -> Path:
    if task not in TASKS or provider not in PROVIDERS:
        raise ValueError("unknown gap-pilot audit scope")
    return RUN / f"audit-{provider}" / task / experiment_id


def scoped_experiment(task: str, provider: str):
    original = load_experiment(config_path(task))
    if tuple(original.outcome_audit["models"]) != HISTORICAL_PANEL:
        raise RuntimeError("saved revision config no longer has the historical panel")
    payload = deepcopy(original.payload)
    payload["execution_audit_models"] = [PROVIDERS[provider][0]]
    payload["dag"]["detect"]["output_dir"] = str(
        audit_dir(task, provider, original.experiment_id)
    )
    scoped = replace(original, payload=payload)
    if scoped.experiment_id != original.experiment_id:
        raise RuntimeError("provider-only audit changed revision experiment identity")
    if tuple(scoped.outcome_audit["models"]) != (PROVIDERS[provider][0],):
        raise RuntimeError("provider-only audit scope differs")
    return scoped


def validate_revision(task: str) -> int:
    experiment = load_experiment(config_path(task))
    study = Path(experiment.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text())
    rows = terminal_records(experiment, ledger)
    if len(rows) != 6 or any(row["status"] != "completed" for row in rows):
        raise RuntimeError(f"{task} revision is not 6/6 complete")
    return len(rows)


def credentials(provider: str) -> None:
    key = PROVIDERS[provider][1]
    value = os.environ.get(key) or dotenv_values(
        "/home/aydanh/repos/rubric_gen/.env.local"
    ).get(key)
    if not value:
        raise RuntimeError(f"configured credential unavailable: {key}")
    os.environ[key] = str(value)


def validate_runtime() -> dict[str, object]:
    runtime = policy()
    if runtime.get("audit_studies") != 3:
        raise RuntimeError("gap-pilot audit owner capacity changed")
    expected = {"openai": 60, "anthropic": 60, "google": 60}
    if runtime.get("audit_provider_concurrency") != expected:
        raise RuntimeError("gap-pilot audit provider capacity changed")
    if (
        int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 4
        or int(os.environ.get("SLURM_MEM_PER_NODE", "0")) < 32768
    ):
        raise RuntimeError("provider audit requires 4 CPU and at least 32 GiB")
    return runtime


def run_scope(task: str, provider: str, workers: int) -> dict[str, object]:
    if (task, provider) not in planned_scopes():
        raise RuntimeError(
            "historical da-26-2 Sol must be reused; duplicate calls are forbidden"
        )
    experiment = scoped_experiment(task, provider)
    output_dir = Path(experiment.dag["detect"]["output_dir"])
    args = argparse.Namespace(max_concurrency=workers, resume=True)
    started = now()
    with audit_output_owner(output_dir):
        exit_code = _run_detect_owned(
            args,
            experiment,
            Path(experiment.dag["revise"]["output_dir"]),
            Path(experiment.dag["paraphrase"]["output_dir"]),
            output_dir,
        )
    if exit_code:
        raise RuntimeError(
            f"{task}/{provider} audit incomplete; saved judgments retained"
        )
    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check

    coverage = check(
        Path(experiment.dag["revise"]["output_dir"]),
        output_dir,
        expected_models=(PROVIDERS[provider][0],),
    )
    if coverage.get("assignment_count") != 6:
        raise RuntimeError(f"{task}/{provider} audit coverage differs from six")
    return {
        "task_id": task,
        "provider_scope": provider,
        "models": list(experiment.outcome_audit["models"]),
        "experiment_id": experiment.experiment_id,
        "study_dir": str(experiment.dag["revise"]["output_dir"]),
        "audit_dir": str(output_dir),
        "max_concurrency": workers,
        "coverage": coverage,
        "started_at": started,
        "finished_at": now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=TASKS, required=True)
    parser.add_argument("--provider", choices=tuple(PROVIDERS), required=True)
    parser.add_argument(
        "--max-concurrency", type=int, default=MAX_CONCURRENCY
    )
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("provider audit must run through Slurm")
    if not 1 <= args.max_concurrency <= MAX_CONCURRENCY:
        raise ValueError("provider audit concurrency must be between 1 and 60")
    commit = clean_commit()
    runtime = validate_runtime()
    assignments = validate_revision(args.task)
    credentials(args.provider)
    owner = (
        RUN
        / "owners"
        / (
            f"audit-{args.provider}-{args.task}-{os.environ['SLURM_JOB_ID']}-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        )
    )
    owner.mkdir(parents=True, exist_ok=False)
    launch = {
        "source_commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "task_id": args.task,
        "provider_scope": args.provider,
        "model": PROVIDERS[args.provider][0],
        "assignment_count": assignments,
        "max_concurrency": args.max_concurrency,
        "runtime_topology": {
            "outer_shard_workers": 1,
            "per_shard_assignment_workers": args.max_concurrency,
            "configured_aggregate_concurrency": runtime[
                "aggregate_concurrency"
            ],
            "provider_request_cap_per_audit_owner": runtime[
                "audit_provider_concurrency"
            ][RUNTIME_PROVIDERS[args.provider]],
            "internal_revision_fanout": 0,
            "maximum_parallel_audit_owners": 3,
            "maximum_total_request_workers_across_owners": 180,
        },
        "expected_wall_time_minutes": EXPECTED_WALL_TIME_MINUTES,
        "runtime": runtime,
        "cpus": int(os.environ["SLURM_CPUS_PER_TASK"]),
        "memory_mb": int(os.environ["SLURM_MEM_PER_NODE"]),
        "gpu_use": "allocated but intentionally unused",
        "started_at": now(),
    }
    write_json_atomic(owner / "launch.json", launch)
    result = run_scope(args.task, args.provider, args.max_concurrency)
    receipt = {
        "kind": "result40-gap-improvement-provider-audit-v1",
        **launch,
        **result,
        "config_sha256": sha256_file(config_path(args.task)),
        "success": True,
    }
    write_json_atomic(owner / "completed.json", receipt)
    status = RUN / "audit-sol-opus-status"
    status.mkdir(parents=True, exist_ok=True)
    write_json_atomic(status / f"{args.task}-{args.provider}.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
