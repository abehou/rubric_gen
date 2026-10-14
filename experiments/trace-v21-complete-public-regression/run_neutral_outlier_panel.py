"""Run a matched neutral-heldout panel on four saved New20 outlier tasks."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run

from run_neutral_heldout5 import (
    RESULT40,
    neutral_scope,
    prepare_neutral_pool,
    run_scores,
    source_targets,
)


TASKS = ("da-26-4", "da-26-2", "da-17-1", "da-17-5")
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-outlier-panel"
)
EXISTING_DA264_POOL = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-heldout5/paraphrases"
)


def configs(task_id: str):
    return (
        RESULT40 / f"configs/{task_id}-static.yaml",
        RESULT40 / f"configs/{task_id}-trace.yaml",
    )


def target_subset(task_id: str, experiment):
    targets = source_targets(experiment)
    if task_id == "da-26-4":
        targets = tuple(target for target in targets if target.replicate != 2)
    expected = 4 if task_id == "da-26-4" else 6
    if len(targets) != expected:
        raise RuntimeError(
            f"{task_id} {experiment.experiment_id}: expected {expected} targets, "
            f"found {len(targets)}"
        )
    return targets


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("neutral outlier panel must run on a Babel compute node")
    completion: dict[str, object] = {
        "kind": "neutral-heldout5-four-outlier-task-panel",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tasks": {},
    }
    for task_id in TASKS:
        static_path, trace_path = configs(task_id)
        trace = load_experiment(trace_path)
        pool = (
            EXISTING_DA264_POOL
            if task_id == "da-26-4"
            else RUN / "paraphrases" / task_id
        )
        neutral = neutral_scope(trace, output_dir=pool)
        if task_id == "da-26-4":
            validate_paraphrase_run(pool, neutral)
            pool_receipt = {"pool": str(pool), "reused": True}
        else:
            pool_receipt = prepare_neutral_pool(neutral, output_dir=pool)
        task_receipt: dict[str, object] = {"pool": pool_receipt}
        for role, config_path in (("static", static_path), ("trace", trace_path)):
            experiment = load_experiment(config_path)
            targets = target_subset(task_id, experiment)
            audit_root = RUN / "rubric-score" / task_id / role
            summary = run_scores(
                neutral,
                targets,
                audit_root=audit_root,
                paraphrase_dir=pool,
                study_dir=RUN / "read-only-source-studies" / task_id / role,
                run_kind=f"neutral-heldout5-outlier-{task_id}-{role}",
            )
            task_receipt[role] = {
                "config": str(config_path),
                "assignment_ids": [target.assignment_id for target in targets],
                "status": summary["status"],
                "successful_judgments": summary["successful_judgments"],
            }
        completion["tasks"][task_id] = task_receipt
        write_json_atomic(RUN / "progress.json", completion)
    completion["finished_at"] = datetime.now(timezone.utc).isoformat()
    completion["status"] = "completed"
    # da-26-4 rep-002 has 40 reusable judgments; this run adds the other 440.
    completion["new_successful_judgments"] = 440
    completion["reused_successful_judgments"] = 40
    write_json_atomic(RUN / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
