"""Score five saved neutral heldouts on matched da-26-4 static artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run

from run_neutral_heldout5 import (
    BUNDLE,
    NEUTRAL_POOL,
    REPAIRED_CONFIG,
    RESULT40,
    neutral_scope,
    run_scores,
    source_targets,
)


STATIC_CONFIG = RESULT40 / "configs/da-26-4-static.yaml"
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-heldout5-static"
)
AUDIT_ROOT = RUN / "rubric-score"


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("neutral static audit must run on a Babel compute node")
    static = load_experiment(STATIC_CONFIG)
    neutral = neutral_scope(load_experiment(REPAIRED_CONFIG))
    validate_paraphrase_run(NEUTRAL_POOL, neutral)
    targets = source_targets(static, replicate=2)
    if len(targets) != 2 or {target.condition_id for target in targets} != {
        "full-static",
        "user-simulator-static",
    }:
        raise RuntimeError("matched static scope must contain rep-002 Full and User")
    summary = run_scores(
        neutral,
        targets,
        audit_root=AUDIT_ROOT,
        run_kind="neutral-heldout5-matched-static-final-rubric-score-only",
    )
    completion = {
        "kind": "neutral-heldout5-da-26-4-rep002-static-completion",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source_config": str(STATIC_CONFIG),
        "neutral_pool": str(NEUTRAL_POOL),
        "target_assignment_ids": [target.assignment_id for target in targets],
        "audit_status": summary["status"],
        "successful_judgments": summary["successful_judgments"],
    }
    RUN.mkdir(parents=True, exist_ok=True)
    write_json_atomic(RUN / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
