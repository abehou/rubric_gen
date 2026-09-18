"""Run the counted first-task Results40 pilot with final experiment identities."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket

from rubric_gen.artifacts.serialization import write_json_atomic

from make_configs import CONDITIONS, RUN
from run import (
    clean_commit,
    complete_shard,
    credentials,
    now,
    runtime,
    uv_stage,
    validate_task_match,
)


TASK = "da-8-1"
SHARDS = ((TASK, "static"), (TASK, "trace"))


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("Results40 pilot requires one 32-CPU Slurm allocation")
    commit = clean_commit()
    capacity = runtime("execute")
    credentials()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    owner = RUN / "owners" / f"pilot-{os.environ['SLURM_JOB_ID']}-{stamp}"
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "launch.json", {
        "mode": "counted-in-cohort-pilot",
        "source_commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "started_at": stamp,
        "tasks": [TASK],
        "conditions": list(CONDITIONS),
        "assignment_count": 12,
        "cpus": int(os.environ["SLURM_CPUS_PER_TASK"]),
        "memory": "256G",
        "runtime": capacity,
        "internal_fanout": 4,
        "shards": [f"{task}-{kind}" for task, kind in SHARDS],
    })

    def one(shard: tuple[str, str]) -> dict:
        task, kind = shard
        result = uv_stage(task, kind, "revise", 6, owner / f"revise-{task}-{kind}.log")
        if result["exit_code"] == 0:
            try:
                result["completed_assignments"] = len(complete_shard(task, kind))
            except Exception as error:
                result["validation_error"] = f"{type(error).__name__}: {error}"
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(one, SHARDS))
    failures = [row for row in rows if row["exit_code"] != 0 or row.get("completed_assignments") != 6]
    if failures:
        raise RuntimeError(f"Results40 pilot retained incomplete shards: {json.dumps(failures)}")
    validate_task_match(TASK)
    receipt = {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": commit,
        "task": TASK,
        "assignment_count": 12,
        "conditions": list(CONDITIONS),
        "shards": rows,
        "finished_at": now(),
    }
    write_json_atomic(RUN / "pilot-completion.json", receipt)
    write_json_atomic(owner / "completed.json", receipt)


if __name__ == "__main__":
    main()
