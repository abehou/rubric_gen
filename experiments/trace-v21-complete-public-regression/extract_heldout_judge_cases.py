"""Extract saved rubric wording and judge reasons for heldout-policy analysis."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.evaluation.evidence_policy import (
    render_sealed_public_evidence,
)
from rubric_gen.submission_revision.experiment import load_experiment

from report_neutral_outlier_panel import panel_root, pool_for
from run_neutral_heldout5 import neutral_jobs, neutral_scope, source_targets
from run_neutral_new20 import COMPLETED_TASKS, PENDING_TASKS, RESULT40, RUN


ROOT = Path(__file__).resolve().parents[2]
CASE_SCOPE = os.environ.get("EVIDENCE_CASE_SCOPE", "saved")
TASK_FILTER = os.environ.get("EVIDENCE_TASK_ID")
REPLICATE_FILTER = (
    int(os.environ["EVIDENCE_REPLICATE"])
    if os.environ.get("EVIDENCE_REPLICATE")
    else None
)
OUTPUT_NAME = (
    "outlier4-evidence.json"
    if CASE_SCOPE == "outlier4"
    else f"new20-remaining16-{TASK_FILTER}-rep{REPLICATE_FILTER:03d}-evidence.json"
    if CASE_SCOPE == "new20_remaining16"
    and TASK_FILTER
    and REPLICATE_FILTER is not None
    else f"new20-remaining16-{TASK_FILTER}-evidence.json"
    if CASE_SCOPE == "new20_remaining16" and TASK_FILTER
    else "new20-remaining16-evidence.json"
    if CASE_SCOPE == "new20_remaining16"
    else "saved-case-evidence.json"
)
OUTPUT = ROOT / "diagnostics/heldout-judge-failure-analysis" / OUTPUT_NAME
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
REVIEW_MODEL = MODELS[0]
SAVED_CASES = (
    ("da-20-4", "static", "Full", 1),
    ("da-20-4", "trace", "Full", 1),
    ("da-5-1", "static", "User", 3),
    ("da-5-1", "trace", "User", 3),
    ("da-26-4", "static", "User", 2),
    ("da-26-4", "trace", "User", 2),
    ("da-24-3", "static", "Full", 1),
    ("da-24-3", "trace", "Full", 1),
    ("da-26-2", "static", "User", 3),
    ("da-26-2", "trace", "User", 3),
    ("da-17-1", "static", "Full", 1),
    ("da-17-1", "trace", "Full", 1),
    ("da-17-5", "static", "User", 2),
    ("da-17-5", "trace", "User", 2),
    ("da-9-7", "static", "User", 1),
    ("da-9-7", "trace", "User", 1),
)
OUTLIER_TASKS = ("da-26-4", "da-26-2", "da-17-1", "da-17-5")


def cases() -> tuple[tuple[str, str, str, int], ...]:
    if CASE_SCOPE == "saved":
        return SAVED_CASES
    if CASE_SCOPE == "outlier4":
        task_ids = OUTLIER_TASKS
        expected = 48
    elif CASE_SCOPE == "new20_remaining16":
        if TASK_FILTER:
            if TASK_FILTER not in PENDING_TASKS:
                raise RuntimeError(
                    f"task is not in the remaining New20 scope: {TASK_FILTER}"
                )
            task_ids = (TASK_FILTER,)
            expected = 4 if REPLICATE_FILTER is not None else 12
        else:
            task_ids = PENDING_TASKS
            expected = 192
    else:
        raise RuntimeError(f"unknown evidence case scope: {CASE_SCOPE}")
    rows = []
    for task_id in task_ids:
        for role in ("static", "trace"):
            experiment = load_experiment(config(task_id, role))
            for target in source_targets(experiment):
                if (
                    REPLICATE_FILTER is not None
                    and target.replicate != REPLICATE_FILTER
                ):
                    continue
                arm = (
                    "User"
                    if target.condition_id.startswith("user-")
                    else "Full"
                )
                rows.append((task_id, role, arm, target.replicate))
    result = tuple(rows)
    if len(result) != expected:
        raise RuntimeError(
            f"expected {expected} {CASE_SCOPE} cases, found {len(result)}"
        )
    return result


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def config(task_id: str, role: str) -> Path:
    return RESULT40 / f"configs/{task_id}-{role}.yaml"


def target_for(experiment, arm: str, replicate: int):
    matches = [
        target
        for target in source_targets(experiment)
        if target.replicate == replicate
        and (
            (arm == "User" and target.condition_id.startswith("user-"))
            or (arm == "Full" and not target.condition_id.startswith("user-"))
        )
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one target for {experiment.experiment_id} {arm} {replicate}"
        )
    return matches[0]


def evaluation(path: Path) -> dict[str, object]:
    payload = read(path)
    return {
        "overall_reasoning": payload.get("overall_reasoning"),
        "criteria": {
            criterion: {
                "level": result.get("level"),
                "points": result.get("points"),
                "reason": result.get("reason"),
            }
            for criterion, result in payload["criteria"].items()
        },
    }


def old_judgments(experiment, target) -> list[dict[str, object]]:
    audit = Path(str(experiment.dag["detect"]["output_dir"]))
    summary = read(audit / "rubric_score/summary.json")
    references = [
        reference
        for reference in summary["records"]
        if reference["assignment_id"] == target.assignment_id
        and reference["model"] in MODELS
        and reference["artifact"] == "final"
        and any(
            role["name"] in {"selected", "holdout"}
            for role in reference["rubric_roles"]
        )
    ]
    rows = []
    for reference in references:
        record = read(
            audit
            / "rubric_score/records"
            / f"{reference['judgment_key']}.json"
        )
        rows.append(
            {
                "score": reference["score"],
                "model": reference["model"],
                "rubric_roles": reference["rubric_roles"],
                "rubric_sha256": record["rubric_sha256"],
                "evaluation": evaluation(Path(str(record["evaluation_path"]))),
            }
        )
    return rows


def neutral_pool(task_id: str) -> Path:
    if task_id in COMPLETED_TASKS:
        return pool_for(task_id)
    return RUN / "paraphrases" / task_id


def neutral_audit_root(task_id: str, role: str, replicate: int) -> Path:
    if task_id in COMPLETED_TASKS:
        return panel_root(task_id, role, replicate)
    return RUN / "rubric-score" / task_id / role


def neutral_judgments(task_id: str, role: str, experiment, target):
    pool = neutral_pool(task_id)
    neutral = neutral_scope(
        load_experiment(config(task_id, "trace")),
        output_dir=pool,
    )
    stage = RubricScoreStage(
        EvaluationConfig(
            experiment=neutral,
            study_dir=RUN / "extract-read-only-source-study" / task_id / role,
            paraphrase_dir=pool,
            output_dir=RUN / "extract-read-only-audit" / task_id / role,
            max_concurrency=1,
            resume=True,
        ),
        (target,),
    )
    root = neutral_audit_root(task_id, role, target.replicate)
    rows = []
    for job in neutral_jobs(stage, (target,), paraphrase_dir=pool):
        if job.model not in MODELS:
            continue
        record = read(root / "records" / f"{job.key}.json")
        rows.append(
            {
                "variant": job.roles[0].variant_index,
                "model": job.model,
                "score": record["score"],
                "rubric_sha256": record["rubric_sha256"],
                "evaluation": evaluation(Path(str(record["evaluation_path"]))),
            }
        )
    return rows


def artifact_evidence(task_id: str, role: str, experiment, target) -> dict[str, str]:
    """Render the exact review inputs used by the saved rubric-score jobs."""

    pool = neutral_pool(task_id)
    neutral = neutral_scope(
        load_experiment(config(task_id, "trace")),
        output_dir=pool,
    )
    stage = RubricScoreStage(
        EvaluationConfig(
            experiment=neutral,
            study_dir=RUN / "extract-read-only-source-study" / task_id / role,
            paraphrase_dir=pool,
            output_dir=RUN / "extract-read-only-audit" / task_id / role,
            max_concurrency=1,
            resume=True,
        ),
        (target,),
    )
    rubric_path = pool / "tasks" / task_id / "variant-000.txt"
    judge = stage._new_judge(
        target=target,
        model=REVIEW_MODEL,
        rubric_path=rubric_path,
        artifact_key="extract-read-only-evidence",
    )
    review_text, answer_text = judge.review_inputs(target.final_submission)
    return {
        "workspace_review": review_text,
        "final_answer": answer_text,
    }


def submission_inventory(target) -> list[dict[str, object]]:
    """List the actual saved final-submission files without interpreting them."""

    rows = []
    for path in sorted(target.final_submission.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rows.append(
            {
                "path": str(path.relative_to(target.final_submission)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def rubric_texts(task_id: str, experiment) -> dict[str, object]:
    old_pool = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    pool = neutral_pool(task_id)
    return {
        "master": (
            experiment.task_dir(task_id)
            / "tests"
            / str(experiment.protocol["rubric_name"])
        ).read_text(encoding="utf-8"),
        "rigorous": {
            str(index): (
                old_pool / "tasks" / task_id / f"variant-{index:03d}.txt"
            ).read_text(encoding="utf-8")
            for index in (2, 3, 4)
        },
        "neutral": {
            str(index): (
                pool / "tasks" / task_id / f"variant-{index:03d}.txt"
            ).read_text(encoding="utf-8")
            for index in range(5)
        },
    }


def main() -> int:
    rows = []
    rubrics = {}
    for task_id, role, arm, replicate in cases():
        experiment = load_experiment(config(task_id, role))
        target = target_for(experiment, arm, replicate)
        rubrics.setdefault(task_id, rubric_texts(task_id, experiment))
        rows.append(
            {
                "task_id": task_id,
                "role": role,
                "arm": arm,
                "replicate": replicate,
                "assignment_id": target.assignment_id,
                "artifact_evidence": artifact_evidence(
                    task_id, role, experiment, target
                ),
                "submission_inventory": submission_inventory(target),
                "sealed_public_evidence": render_sealed_public_evidence(
                    target.final_submission
                ),
                "historical_selected_and_rigorous": old_judgments(
                    experiment, target
                ),
                "uniform_neutral": neutral_judgments(
                    task_id, role, experiment, target
                ),
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        OUTPUT,
        {
            "kind": "heldout-judge-failure-saved-case-evidence",
            "case_scope": CASE_SCOPE,
            "task_filter": TASK_FILTER,
            "replicate_filter": REPLICATE_FILTER,
            "models": list(MODELS),
            "cases": rows,
            "rubrics": rubrics,
        },
    )
    print(OUTPUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
