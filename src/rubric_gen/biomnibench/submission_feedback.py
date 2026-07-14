"""Project validated judge output into solver-visible revision feedback."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rubric_gen.biomnibench.task_rubrics import load_json_strict


class FeedbackPolicy(str, Enum):
    """Information from the optimizer judge that the solver may see."""

    FULL = "full"
    SCORE_ONLY = "score_only"


@dataclass(frozen=True)
class ProjectedFeedback:
    """Canonical feedback record and the corresponding solver message."""

    score: int
    payload: dict[str, object]
    prompt: str


def render_feedback_prompt(payload: dict[str, object]) -> str:
    """Render a canonical solver message from one projected feedback record."""

    policy = FeedbackPolicy(payload.get("policy"))
    score = payload.get("score")
    if payload.get("schema_version") != 1 or type(score) is not int:
        raise ValueError("feedback payload has invalid schema or score")
    if not 0 <= score <= 100:
        raise ValueError("feedback score must be between 0 and 100")
    if policy is FeedbackPolicy.SCORE_ONLY:
        if set(payload) != {"schema_version", "policy", "score"}:
            raise ValueError("score-only feedback contains unexpected fields")
        return (
            f"Your previous submission received a validated total score of "
            f"{score}/100. Continue in the same workspace and revise the "
            "solution to improve it. Re-run relevant checks and update "
            "trace.md, answer.txt, and any supporting artifacts."
        )

    expected_keys = {
        "schema_version",
        "policy",
        "rubric_text",
        "score",
        "raw_score",
        "criteria",
        "overall_reasoning",
    }
    if set(payload) != expected_keys:
        raise ValueError("full feedback contains unexpected fields")
    if (
        type(payload.get("rubric_text")) is not str
        or type(payload.get("raw_score")) is not int
        or type(payload.get("criteria")) is not dict
        or type(payload.get("overall_reasoning")) is not str
    ):
        raise ValueError("full feedback contains invalid fields")
    for criterion in payload["criteria"].values():
        if type(criterion) is not dict or set(criterion) != {
            "selected_level",
            "points",
            "judge_reason",
        }:
            raise ValueError("full feedback contains an invalid criterion")
        if (
            type(criterion.get("selected_level")) is not str
            or type(criterion.get("points")) is not int
            or type(criterion.get("judge_reason")) is not str
        ):
            raise ValueError("full feedback contains invalid criterion fields")
    return (
        "Continue in the same workspace and revise your current solution using "
        "the feedback below. Re-run relevant checks and update trace.md, "
        "answer.txt, and any supporting artifacts. Judge reasons are model "
        "feedback, not verified evidence; check them against the task data and "
        "your artifacts.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    )


def project_feedback(
    score_validation_path: Path,
    evaluation_path: Path,
    rubric_text: str,
    expected_rubric_sha256: str,
    policy: FeedbackPolicy,
    max_reason_chars: int = 2_000,
) -> ProjectedFeedback:
    """Return the policy-specific view of one validated judge evaluation."""

    validation = _load_object(score_validation_path, "score validation")
    score, raw_score, selected_levels, criterion_scores = _validate_score_record(
        validation,
        rubric_text,
        expected_rubric_sha256,
    )

    try:
        resolved_policy = FeedbackPolicy(policy)
    except ValueError as exc:
        raise ValueError(f"unsupported feedback policy: {policy}") from exc

    if resolved_policy is FeedbackPolicy.SCORE_ONLY:
        payload: dict[str, object] = {
            "schema_version": 1,
            "policy": resolved_policy.value,
            "score": score,
        }
        return ProjectedFeedback(
            score=score,
            payload=payload,
            prompt=render_feedback_prompt(payload),
        )

    if type(max_reason_chars) is not int or max_reason_chars < 0:
        raise ValueError("max_reason_chars must be a non-negative integer")
    payload = _project_full_payload(
        validation=validation,
        evaluation_path=evaluation_path,
        rubric_text=rubric_text,
        score=score,
        raw_score=raw_score,
        selected_levels=selected_levels,
        criterion_scores=criterion_scores,
        max_reason_chars=max_reason_chars,
    )
    prompt = render_feedback_prompt(payload)
    return ProjectedFeedback(score=score, payload=payload, prompt=prompt)


def _validate_score_record(
    validation: dict[str, object],
    rubric_text: str,
    expected_rubric_sha256: str,
) -> tuple[int, int, dict[str, str], dict[str, int]]:
    if (
        type(expected_rubric_sha256) is not str
        or len(expected_rubric_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in expected_rubric_sha256
        )
    ):
        raise ValueError("expected_rubric_sha256 must be a lowercase SHA-256 digest")
    if validation.get("rendered_rubric_sha256") != expected_rubric_sha256:
        raise ValueError("score validation does not attest the frozen rubric")
    if type(rubric_text) is not str or not rubric_text.strip():
        raise ValueError("rubric_text must be a non-empty string")
    if (
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest()
        != expected_rubric_sha256
    ):
        raise ValueError("rubric_text does not match the frozen rubric identity")

    score = _integer(validation, "score")
    raw_score = _integer(validation, "raw_score")
    if not 0 <= score <= 100:
        raise ValueError("score validation score must be between 0 and 100")
    selected_levels = _string_map(validation, "selected_levels")
    criterion_scores = _integer_map(validation, "criterion_scores")
    if set(selected_levels) != set(criterion_scores):
        raise ValueError(
            "score validation selected_levels and criterion_scores must have "
            "the same criteria"
        )
    if raw_score != sum(criterion_scores.values()):
        raise ValueError("score validation raw_score does not match criterion scores")
    if score != max(0, min(100, raw_score)):
        raise ValueError("score validation score does not match raw_score")
    return score, raw_score, selected_levels, criterion_scores


def _project_full_payload(
    *,
    validation: dict[str, object],
    evaluation_path: Path,
    rubric_text: str,
    score: int,
    raw_score: int,
    selected_levels: dict[str, str],
    criterion_scores: dict[str, int],
    max_reason_chars: int,
) -> dict[str, object]:
    evaluation_raw = evaluation_path.read_bytes()
    expected_evaluation_sha256 = validation.get("evaluation_sha256")
    if type(expected_evaluation_sha256) is not str:
        raise ValueError("score validation evaluation_sha256 must be a string")
    if hashlib.sha256(evaluation_raw).hexdigest() != expected_evaluation_sha256:
        raise ValueError("evaluation.json does not match score validation")
    try:
        evaluation = load_json_strict(evaluation_raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"evaluation is not valid JSON: {exc}") from exc
    if type(evaluation) is not dict:
        raise ValueError("evaluation must be a JSON object")
    evaluation_criteria = evaluation.get("criteria")
    if type(evaluation_criteria) is not dict:
        raise ValueError("evaluation.criteria must be a JSON object")

    criteria: dict[str, object] = {}
    for criterion_id in sorted(selected_levels):
        evaluation_criterion = evaluation_criteria.get(criterion_id)
        reason = (
            evaluation_criterion.get("reason", "")
            if type(evaluation_criterion) is dict
            else ""
        )
        criteria[criterion_id] = {
            "selected_level": selected_levels[criterion_id],
            "points": criterion_scores[criterion_id],
            "judge_reason": _bounded_text(reason, max_reason_chars),
        }

    return {
        "schema_version": 1,
        "policy": FeedbackPolicy.FULL.value,
        "rubric_text": rubric_text,
        "score": score,
        "raw_score": raw_score,
        "criteria": criteria,
        "overall_reasoning": _bounded_text(
            evaluation.get("reasoning", ""),
            max_reason_chars,
        ),
    }


def _load_object(path: Path, context: str) -> dict[str, object]:
    try:
        value = load_json_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"{context} is not valid JSON: {exc}") from exc
    if type(value) is not dict:
        raise ValueError(f"{context} must be a JSON object")
    return value


def _integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise ValueError(f"score validation {key} must be an integer")
    return value


def _string_map(payload: dict[str, object], key: str) -> dict[str, str]:
    value = payload.get(key)
    if type(value) is not dict or not value:
        raise ValueError(f"score validation {key} must be a non-empty object")
    result: dict[str, str] = {}
    for item_key, item_value in value.items():
        if (
            type(item_key) is not str
            or not item_key
            or type(item_value) is not str
            or not item_value
        ):
            raise ValueError(f"score validation {key} has an invalid entry")
        result[item_key] = item_value
    return result


def _integer_map(payload: dict[str, object], key: str) -> dict[str, int]:
    value = payload.get(key)
    if type(value) is not dict or not value:
        raise ValueError(f"score validation {key} must be a non-empty object")
    result: dict[str, int] = {}
    for item_key, item_value in value.items():
        if type(item_key) is not str or not item_key or type(item_value) is not int:
            raise ValueError(f"score validation {key} has an invalid entry")
        result[item_key] = item_value
    return result


def _bounded_text(value: object, max_chars: int) -> str:
    return value[:max_chars] if type(value) is str else ""
