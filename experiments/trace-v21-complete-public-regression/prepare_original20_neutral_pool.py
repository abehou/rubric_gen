"""Generate the five uniform-neutral heldouts used by Original20 reanalysis."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.paraphrases import (
    ParaphraseRunConfig,
    ParaphraseRunner,
)
from rubric_gen.submission_revision.paraphrase_protocol import UNIFORM_NEUTRAL
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run

from original20_evidence import (
    NEUTRAL_POOL,
    RUN,
    TASKS,
    neutral_experiment,
    targets,
)


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Original20 neutral pool must run on a Babel compute node")
    source_targets = targets()
    expected_counts = {"static_full": 60, "static_user": 60, "trace": 120}
    actual_counts = {name: len(rows) for name, rows in source_targets.items()}
    if actual_counts != expected_counts:
        raise RuntimeError(
            f"Original20 saved-artifact coverage changed: {actual_counts}"
        )
    experiment = neutral_experiment()
    if tuple(experiment.task_ids) != TASKS:
        raise RuntimeError("Original20 neutral-pool scope changed")
    runner = ParaphraseRunner(
        ParaphraseRunConfig(
            experiment=experiment,
            output_dir=NEUTRAL_POOL,
            max_concurrency=2,
        )
    )
    if runner.run() != 0:
        raise RuntimeError("Original20 neutral paraphrase generation failed")
    validate_paraphrase_run(NEUTRAL_POOL, experiment)

    hashes = {}
    for task_id in TASKS:
        paths = tuple(
            NEUTRAL_POOL / "tasks" / task_id / f"variant-{index:03d}.txt"
            for index in range(5)
        )
        digests = tuple(sha256_file(path) for path in paths)
        master = (
            experiment.task_dir(task_id)
            / "tests"
            / str(experiment.protocol["rubric_name"])
        )
        if len(set(digests) | {sha256_file(master)}) != 6:
            raise RuntimeError(f"neutral heldout duplicate detected: {task_id}")
        hashes[task_id] = {
            str(index): digest for index, digest in enumerate(digests)
        }
    receipt = {
        "kind": "original20-uniform-neutral-five-heldout-pool",
        "status": "completed",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "prompt_policy": UNIFORM_NEUTRAL,
        "tasks": list(TASKS),
        "count_per_task": 5,
        "saved_artifact_counts": actual_counts,
        "variant_sha256s": hashes,
    }
    write_json_atomic(RUN / "paraphrase-completion.json", receipt)
    print(json.dumps({
        "status": "completed",
        "tasks": len(TASKS),
        "paraphrases": len(TASKS) * 5,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
