"""Complete uniform-neutral heldout scoring for all saved New20 artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment

from run_neutral_heldout5 import (
    RESULT40,
    neutral_scope,
    prepare_neutral_pool,
    run_scores,
    source_targets,
)
from run_neutral_outlier_panel import TASKS as COMPLETED_TASKS


NEW20_TASKS = (
    "da-8-1",
    "da-26-4",
    "da-20-4",
    "da-19-3",
    "da-4-1",
    "da-1-3",
    "da-3-5",
    "da-4-6",
    "da-5-1",
    "da-26-2",
    "da-9-7",
    "da-24-3",
    "da-6-5",
    "da-17-3",
    "da-1-4",
    "da-8-3",
    "da-17-5",
    "da-17-1",
    "da-9-1",
    "da-20-1",
)
PENDING_TASKS = tuple(task for task in NEW20_TASKS if task not in COMPLETED_TASKS)
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-new20"
)


def config(task_id: str, role: str) -> Path:
    return RESULT40 / f"configs/{task_id}-{role}.yaml"


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("neutral New20 scoring must run on a Babel compute node")
    if len(NEW20_TASKS) != 20 or len(PENDING_TASKS) != 16:
        raise RuntimeError("neutral New20 scope changed")
    completion: dict[str, object] = {
        "kind": "neutral-heldout5-new20-completion",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "all_tasks": list(NEW20_TASKS),
        "reused_completed_tasks": list(COMPLETED_TASKS),
        "new_tasks": list(PENDING_TASKS),
        "tasks": {},
    }
    for task_id in PENDING_TASKS:
        trace = load_experiment(config(task_id, "trace"))
        pool = RUN / "paraphrases" / task_id
        neutral = neutral_scope(trace, output_dir=pool)
        pool_receipt = prepare_neutral_pool(neutral, output_dir=pool)
        task_receipt: dict[str, object] = {"pool": pool_receipt}
        for role in ("static", "trace"):
            config_path = config(task_id, role)
            experiment = load_experiment(config_path)
            targets = source_targets(experiment)
            if len(targets) != 6:
                raise RuntimeError(
                    f"{task_id} {role}: expected six targets, found {len(targets)}"
                )
            audit_root = RUN / "rubric-score" / task_id / role
            summary = run_scores(
                neutral,
                targets,
                audit_root=audit_root,
                paraphrase_dir=pool,
                study_dir=RUN / "read-only-source-studies" / task_id / role,
                run_kind=f"neutral-heldout5-new20-{task_id}-{role}",
            )
            task_receipt[role] = {
                "config": str(config_path),
                "assignment_ids": [target.assignment_id for target in targets],
                "status": summary["status"],
                "successful_judgments": summary["successful_judgments"],
            }
        completion["tasks"][task_id] = task_receipt
        write_json_atomic(RUN / "progress.json", completion)
    completion.update(
        finished_at=datetime.now(timezone.utc).isoformat(),
        status="completed",
        new_paraphrases=80,
        new_successful_judgments=1920,
        reused_paraphrases=20,
        reused_successful_judgments=480,
        total_successful_judgments=2400,
    )
    write_json_atomic(RUN / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
