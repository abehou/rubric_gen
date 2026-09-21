"""Run or audit the counted five-task gap-improvement pilot."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment

from make_configs import BUNDLE, CONDITIONS, PANEL, ROOT, RUN, SMOKE_TASK, TASKS, config_path
from prepare import sha


UV = Path("/home/aydanh/tools/uv/uv")
PYTHON = Path("/home/aydanh/repos/rubric_gen/.venv/bin/python")


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
        raise RuntimeError("pilot source must be a clean commit")
    return commit


def credentials(mode: str) -> None:
    required = (
        ("OPENAI_API_KEY",)
        if mode == "execute"
        else ("OPENAI_API_KEY", "GEMINI_API_KEY")
    )
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in required:
        value = values.get(key)
        if not value:
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(value)


def environment() -> dict[str, str]:
    result = dict(os.environ)
    result.update({
        "PYTHONPATH": str(ROOT / "src"),
        "UV_PROJECT_ENVIRONMENT": str(PYTHON.parent.parent),
    })
    return result


def selected_tasks(scope: str) -> tuple[str, ...]:
    if scope == "smoke":
        return (SMOKE_TASK,)
    if scope == "remaining":
        return tuple(task for task in TASKS if task != SMOKE_TASK)
    if scope == "all":
        return TASKS
    raise ValueError(f"unknown scope: {scope}")


def experiment(task: str):
    return load_experiment(config_path(task))


def stage(task: str, mode: str, workers: int, log: Path) -> dict[str, object]:
    verb = "revise" if mode == "execute" else "detect"
    command = [
        str(UV), "run", "--no-sync", "rubric-gen", verb,
        "--experiment", str(config_path(task)),
        "--max-concurrency", str(workers), "--resume",
    ]
    started = now()
    with log.open("a") as output:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment(),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    return {
        "task_id": task,
        "mode": mode,
        "exit_code": result.returncode,
        "started_at": started,
        "finished_at": now(),
        "log": str(log),
    }


def completed_assignments(task: str) -> int:
    exp = experiment(task)
    study = Path(exp.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text())
    rows = terminal_records(exp, ledger)
    if len(rows) != 6 or any(row["status"] != "completed" for row in rows):
        raise RuntimeError(f"{task} is not 6/6 complete")
    return len(rows)


def validate_audit(task: str) -> dict[str, object]:
    import sys
    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check

    exp = experiment(task)
    result = check(
        Path(exp.dag["revise"]["output_dir"]),
        Path(exp.dag["detect"]["output_dir"]),
        expected_models=PANEL,
    )
    if result.get("assignment_count") != 6:
        raise RuntimeError(f"{task} audit does not cover six assignments")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("execute", "audit"))
    parser.add_argument("--scope", choices=("smoke", "remaining", "all"), required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("pilot execution requires a Slurm compute node")
    commit = clean_commit()
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 3:
        raise RuntimeError("shared runtime policy changed")
    credentials(args.mode)
    tasks = selected_tasks(args.scope)
    workers = 6 if args.mode == "execute" else 12
    parallel = min(len(tasks), 4 if args.mode == "execute" else 3)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    owner = RUN / "owners" / f"{args.mode}-{args.scope}-{os.environ['SLURM_JOB_ID']}-{stamp}"
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "launch.json", {
        "mode": args.mode,
        "scope": args.scope,
        "source_commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "started_at": now(),
        "tasks": list(tasks),
        "conditions": list(CONDITIONS),
        "assignment_count": 6 * len(tasks),
        "per_task_concurrency": workers,
        "task_workers": parallel,
        "runtime": runtime,
    })

    def one(task: str) -> dict[str, object]:
        row = stage(task, args.mode, workers, owner / f"{args.mode}-{task}.log")
        if row["exit_code"] == 0:
            try:
                row["coverage"] = (
                    completed_assignments(task)
                    if args.mode == "execute"
                    else validate_audit(task)
                )
            except Exception as error:
                row["validation_error"] = f"{type(error).__name__}: {error}"
        return row

    rows = []
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = {executor.submit(one, task): task for task in tasks}
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            print(json.dumps(row), flush=True)
    failed = [
        row for row in rows
        if row["exit_code"] != 0 or "validation_error" in row
    ]
    receipt = {
        "success": not failed,
        "mode": args.mode,
        "scope": args.scope,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": commit,
        "tasks": list(tasks),
        "configs": {
            task: {
                "experiment_id": experiment(task).experiment_id,
                "sha256": sha(config_path(task)),
            }
            for task in tasks
        },
        "rows": rows,
        "finished_at": now(),
    }
    write_json_atomic(RUN / f"{args.mode}-{args.scope}-completion.json", receipt)
    write_json_atomic(owner / "completed.json", receipt)
    if failed:
        raise RuntimeError(f"pilot {args.mode}/{args.scope} incomplete: {failed}")


if __name__ == "__main__":
    main()
