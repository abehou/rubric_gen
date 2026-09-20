"""Frozen Results40 revision and missing-only three-auditor audit owner."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources

from make_configs import BUNDLE, CONDITIONS, ROOT, RUN, SHARDS, TASKS, config_path
from prepare import PANEL, sha
from audit_scope import (
    GEMINI_PANEL,
    SOL_OPUS_PANEL,
    THREE_MODEL_PANEL,
    all_gemini_scopes,
    historical_revision_prompt,
    new20_sol_opus_scopes,
)

UV = Path("/home/aydanh/tools/uv/uv")
PYTHON = Path("/home/aydanh/repos/rubric_gen/.venv/bin/python")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def credentials(mode: str) -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    keys = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    if mode == "audit":
        keys = (*keys, "GEMINI_API_KEY")
    for key in keys:
        if not values.get(key):
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(values[key])


def clean_commit() -> str:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty.strip():
        raise RuntimeError("frozen Results40 worktree is not clean")
    return commit


def config(task: str, kind: str) -> Path:
    return config_path(task, kind)


def experiment(task: str, kind: str):
    return load_experiment(config(task, kind))


def runtime(mode: str) -> dict:
    value = policy()
    if value["aggregate_concurrency"] != 60 or value["audit_studies"] != 3:
        raise RuntimeError("Results40 runtime owner capacity changed")
    expected_audit = {"openai": 60, "anthropic": 60, "google": 60}
    if value.get("audit_provider_concurrency") != expected_audit:
        raise RuntimeError("Results40 Sol/Opus/Gemini provider partitions changed")
    return {
        **value,
        "stage_workers": revision_shard_workers() * revision_assignment_workers() if mode == "execute" else 180,
        "revision_shard_workers": revision_shard_workers() if mode == "execute" else None,
        "revision_assignment_workers": revision_assignment_workers() if mode == "execute" else None,
    }


def revision_shard_workers() -> int:
    workers = int(os.environ.get("RESULT40_SHARD_WORKERS", "10"))
    if not 1 <= workers <= 10:
        raise RuntimeError("RESULT40_SHARD_WORKERS must be between 1 and 10")
    return workers


def revision_assignment_workers() -> int:
    workers = int(os.environ.get("RESULT40_ASSIGNMENT_WORKERS", "6"))
    if not 1 <= workers <= 6:
        raise RuntimeError("RESULT40_ASSIGNMENT_WORKERS must be between 1 and 6")
    return workers


def audit_scope_workers(models: tuple[str, ...]) -> int:
    if models == SOL_OPUS_PANEL:
        return 120
    if models == GEMINI_PANEL:
        return 2
    raise RuntimeError(f"unsupported Results40 audit panel: {models}")


def owner(mode: str, commit: str, capacity: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = RUN / "owners" / f"{mode}-{os.environ['SLURM_JOB_ID']}-{stamp}"
    root.mkdir(parents=True, exist_ok=False)
    write_json_atomic(root / "launch.json", {
        "mode": mode,
        "source_commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "started_at": stamp,
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignment_count": 240,
        "cpus": int(os.environ["SLURM_CPUS_PER_TASK"]),
        "memory_mb": int(os.environ["SLURM_MEM_PER_NODE"]),
        "runtime": capacity,
        "internal_fanout": 4,
        "command": sys.argv,
    })
    return root


def environment() -> dict:
    result = dict(os.environ)
    result.update({
        "PYTHONPATH": str(ROOT / "src"),
        "UV_PROJECT_ENVIRONMENT": str(PYTHON.parent.parent),
    })
    return result


def uv_stage(task: str, kind: str, stage: str, workers: int, log: Path) -> dict:
    command = [
        str(UV), "run", "--no-sync", "rubric-gen", stage,
        "--experiment", str(config(task, kind)),
        "--max-concurrency", str(workers), "--resume",
    ]
    started = now()
    with log.open("a") as output:
        completed = subprocess.run(command, cwd=ROOT, env=environment(), stdout=output, stderr=subprocess.STDOUT)
    return {"task_id": task, "shard": kind, "stage": stage, "exit_code": completed.returncode, "started_at": started, "finished_at": now(), "log": str(log)}


def audit_stage(name: str, exp, workers: int, log: Path) -> dict:
    """Run the native detect implementation for one in-memory audit scope."""

    from rubric_gen.runtime.audit_execution import audit_output_owner
    from rubric_gen.submission_revision.commands import _run_detect_owned

    started = now()
    output_dir = Path(exp.dag["detect"]["output_dir"])
    args = argparse.Namespace(max_concurrency=workers, resume=True)
    exit_code = 1
    error = None
    category = None
    try:
        with log.open("a") as output, redirect_stdout(output), redirect_stderr(output):
            with audit_output_owner(output_dir):
                with historical_revision_prompt(name, exp):
                    exit_code = _run_detect_owned(
                        args,
                        exp,
                        Path(exp.dag["revise"]["output_dir"]),
                        Path(exp.dag["paraphrase"]["output_dir"]),
                        output_dir,
                    )
    except Exception as exc:
        from rubric_gen.runtime.failures import failure_category

        error = f"{type(exc).__name__}: {exc}"
        category = failure_category(exc)
    return {
        "scope": name,
        "stage": "detect",
        "models": list(exp.outcome_audit["models"]),
        "experiment_id": exp.experiment_id,
        "study_dir": str(exp.dag["revise"]["output_dir"]),
        "audit_dir": str(output_dir),
        "exit_code": int(exit_code),
        "error": error,
        "failure_category": category,
        "started_at": started,
        "finished_at": now(),
        "log": str(log),
    }


def complete_shard(task: str, kind: str) -> list[dict]:
    exp = experiment(task, kind)
    study = Path(exp.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text())
    rows = terminal_records(exp, ledger)
    if len(rows) != 6 or any(row["status"] != "completed" for row in rows):
        raise RuntimeError(f"{task}/{kind} is not 6/6 complete")
    # StudyRunner performs full artifact/hash validation before it changes an
    # assignment record to completed.  Repeating that scan here re-read large
    # immutable workspaces and exhausted several recovery wall-time limits.
    # Reopen the exact sources through the audit target loader instead: this
    # rechecks study/producer identity, terminal state, rubric generations and
    # the concrete initial/final targets without duplicating workspace hashing.
    sources = resolve_study_sources(study, exp)
    targets = load_evaluation_targets(EvaluationConfig(
        experiment=exp,
        study_dir=study,
        paraphrase_dir=Path(exp.dag["paraphrase"]["output_dir"]),
        output_dir=Path(exp.dag["detect"]["output_dir"]),
        max_concurrency=6,
        resume=True,
    ), sources)
    expected = {row["assignment_id"] for row in rows}
    if len(targets) != 6 or {target.assignment_id for target in targets} != expected:
        raise RuntimeError(f"{task}/{kind} audit target scope differs from completed assignments")
    return rows


def validate_task_match(task: str) -> None:
    by_replicate = {}
    conditions = set()
    for kind in ("static", "trace"):
        exp = experiment(task, kind)
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for row in terminal_records(exp, ledger):
            assignment = assignments[row["assignment_id"]]
            manifest = json.loads((study / row["experiment_dir"] / "manifest.json").read_text())
            by_replicate.setdefault(assignment.replicate, set()).add(manifest["seed_sha256"])
            conditions.add(assignment.condition_id)
    if conditions != set(CONDITIONS) or set(by_replicate) != {1, 2, 3} or any(len(value) != 1 for value in by_replicate.values()):
        raise RuntimeError(f"{task} four conditions do not share matched initial submissions")


def execute(path: Path) -> None:
    status_path = RUN / "revision-status.json"
    if status_path.exists():
        shutil.copyfile(status_path, path / "previous-revision-status.json")
    workers = revision_shard_workers()
    assignment_workers = revision_assignment_workers()
    state = {
        "job_id": os.environ["SLURM_JOB_ID"],
        "started_at": now(),
        "shard_workers": workers,
        "maximum_assignment_workers": workers * assignment_workers,
        "tasks": {},
    }
    state_lock = threading.Lock()
    write_json_atomic(status_path, state)
    def one(shard: tuple[str, str]) -> dict:
        task, kind = shard
        result = uv_stage(task, kind, "revise", assignment_workers, path / f"revise-{task}-{kind}.log")
        if result["exit_code"] == 0:
            try:
                result["completed_assignments"] = len(complete_shard(task, kind))
            except Exception as error:
                result["validation_error"] = f"{type(error).__name__}: {error}"
        with state_lock:
            state["tasks"][f"{task}-{kind}"] = result
            write_json_atomic(status_path, state)
        return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, shard): shard for shard in SHARDS}
        for future in as_completed(futures):
            result = future.result()
            print(json.dumps(result), flush=True)
    failures = [row for row in state["tasks"].values() if row["exit_code"] != 0 or row.get("completed_assignments") != 6]
    state["finished_at"] = now()
    state["complete"] = not failures
    write_json_atomic(status_path, state)
    if failures:
        raise RuntimeError(f"Results40 revision retained incomplete shards: {[(r['task_id'], r['shard']) for r in failures]}")
    for task in TASKS:
        validate_task_match(task)
    write_json_atomic(RUN / "revision-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "assignment_count": 240,
        "tasks": list(TASKS),
        "configs": {f"{task}-{kind}": {"experiment_id": experiment(task, kind).experiment_id, "sha256": sha(config(task, kind))} for task, kind in SHARDS},
        "finished_at": now(),
    })


def check_revision_receipt() -> None:
    receipt = json.loads((RUN / "revision-completion.json").read_text())
    if (
        receipt.get("success") is not True
        or receipt.get("assignment_count") != 240
        or tuple(receipt.get("tasks", ())) != TASKS
    ):
        raise RuntimeError("Results40 revision completion receipt is unavailable")
    for task, kind in SHARDS:
        exp = experiment(task, kind)
        expected = {"experiment_id": exp.experiment_id, "sha256": sha(config(task, kind))}
        if receipt.get("configs", {}).get(f"{task}-{kind}") != expected:
            raise RuntimeError(f"Results40 completed config differs for {task}/{kind}")
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        rows = terminal_records(exp, ledger)
        if len(rows) != 6 or any(row["status"] != "completed" for row in rows):
            raise RuntimeError(f"Results40 completed ledger differs for {task}/{kind}")


def audit(path: Path) -> None:
    check_revision_receipt()
    status_path = RUN / "audit-status.json"
    status = {
        "job_id": os.environ["SLURM_JOB_ID"],
        "started_at": now(),
        "panels": {
            "sol_opus": list(SOL_OPUS_PANEL),
            "gemini": list(GEMINI_PANEL),
            "three_model": list(THREE_MODEL_PANEL),
        },
        "scopes": {},
    }
    write_json_atomic(status_path, status)
    failures = []
    # Finish the already-authoritative Sol+Opus panel first, then add Gemini
    # without placing a Google access failure between Sol/Opus and completion.
    scopes = (*new20_sol_opus_scopes(), *all_gemini_scopes())
    for name, exp in scopes:
        # Gemini's 20M input-token/minute quota was still exceeded twice with
        # four request workers on the long original20 inputs.  Two workers keep
        # the unchanged requests below that provider limit; the sealed Google
        # provider partition remains 60 and Sol/Opus remains 60+60.
        workers = audit_scope_workers(tuple(exp.outcome_audit["models"]))
        result = audit_stage(name, exp, workers, path / f"detect-{name}.log")
        status["scopes"][name] = result
        write_json_atomic(status_path, status)
        print(json.dumps(result), flush=True)
        if result["exit_code"]:
            failures.append(name)
            # A Gemini failure on the first counted scope is the live access
            # test. Preserve it and do not repeat the same provider failure
            # across the remaining 42 scopes.
            if tuple(exp.outcome_audit["models"]) == GEMINI_PANEL:
                status["gemini_stopped_after_first_failed_scope"] = name
                write_json_atomic(status_path, status)
                break
    status["finished_at"] = now()
    status["complete"] = not failures
    write_json_atomic(status_path, status)
    if failures:
        raise RuntimeError(f"Results40 audit retained incomplete tasks: {failures}")
    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check
    coverage = {}
    for name, exp in scopes:
        coverage[name] = check(
            Path(exp.dag["revise"]["output_dir"]),
            Path(exp.dag["detect"]["output_dir"]),
            expected_models=tuple(exp.outcome_audit["models"]),
        )
        expected = 6 if name.startswith("new20-") else (
            120 if name == "old20-current-gemini" else 60
        )
        if coverage[name].get("assignment_count") != expected:
            raise RuntimeError(
                f"{name} audit assignment coverage differs from {expected}"
            )
    write_json_atomic(RUN / "audit-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "panels": status["panels"],
        "coverage": coverage,
        "finished_at": now(),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("execute", "audit"))
    args = parser.parse_args()
    expected_cpus = int(os.environ.get("RESULT40_EXPECTED_CPUS", "32"))
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != expected_cpus:
        raise RuntimeError(f"Results40 production requires one {expected_cpus}-CPU Slurm allocation")
    commit = clean_commit()
    capacity = runtime(args.mode)
    for task, kind in SHARDS:
        exp = experiment(task, kind)
        if len(exp.execution_assignments) != 6 or tuple(exp.outcome_audit["models"]) != PANEL:
            raise RuntimeError(f"frozen Results40 task shard changed: {task}/{kind}")
    credentials(args.mode)
    path = owner(args.mode, commit, capacity)
    (execute if args.mode == "execute" else audit)(path)
    write_json_atomic(path / "completed.json", {"success": True, "finished_at": now()})


if __name__ == "__main__":
    main()
