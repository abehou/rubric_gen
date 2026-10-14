"""Extract one Original20 task/replicate evidence batch from saved artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.evaluation.evidence_policy import (
    render_sealed_public_evidence,
)

from original20_evidence import (
    EVIDENCE_ROOT,
    NEUTRAL_POOL,
    case_plan,
    neutral_experiment,
    target_for,
)


MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
TASK_ID = os.environ.get("EVIDENCE_TASK_ID", "")
REPLICATE = int(os.environ.get("EVIDENCE_REPLICATE", "0"))


def review_inputs(target) -> dict[str, str]:
    neutral = neutral_experiment()
    stage = RubricScoreStage(
        EvaluationConfig(
            experiment=neutral,
            study_dir=EVIDENCE_ROOT / "read-only-study" / TASK_ID,
            paraphrase_dir=NEUTRAL_POOL,
            output_dir=EVIDENCE_ROOT / "read-only-audit" / TASK_ID,
            max_concurrency=1,
            resume=True,
        ),
        (target,),
    )
    judge = stage._new_judge(
        target=target,
        model=MODELS[0],
        rubric_path=NEUTRAL_POOL / "tasks" / TASK_ID / "variant-000.txt",
        artifact_key="original20-evidence-read-only",
    )
    review, answer = judge.review_inputs(target.final_submission)
    return {"workspace_review": review, "final_answer": answer}


def inventory(target) -> list[dict[str, object]]:
    rows = []
    for path in sorted(target.final_submission.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rows.append({
            "path": str(path.relative_to(target.final_submission)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def main() -> int:
    cases = []
    for role, arm in case_plan(TASK_ID, REPLICATE):
        target = target_for(TASK_ID, role, arm, REPLICATE)
        cases.append({
            "task_id": TASK_ID,
            "role": role,
            "arm": arm,
            "replicate": REPLICATE,
            "assignment_id": target.assignment_id,
            "artifact_evidence": review_inputs(target),
            "submission_inventory": inventory(target),
            "sealed_public_evidence": render_sealed_public_evidence(
                target.final_submission
            ),
        })
    rubrics = {
        str(index): (
            NEUTRAL_POOL / "tasks" / TASK_ID / f"variant-{index:03d}.txt"
        ).read_text(encoding="utf-8")
        for index in range(5)
    }
    output = EVIDENCE_ROOT / TASK_ID / f"rep-{REPLICATE:03d}.json"
    write_json_atomic(output, {
        "kind": "original20-evidence-calibrated-heldout-input",
        "case_scope": "original20",
        "task_filter": TASK_ID,
        "replicate_filter": REPLICATE,
        "models": list(MODELS),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "cases": cases,
        "rubrics": {TASK_ID: {"neutral": rubrics}},
    })
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
