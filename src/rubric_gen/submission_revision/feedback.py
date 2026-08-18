"""Project validated judge output into solver-visible revision feedback."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import Path

from rubric_gen.submission_revision.prompts import PromptProfile, revision_guidance
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
    parse_score_normalization_maximum,
)
from rubric_gen.submission_revision.rubrics.schema import load_json_strict
from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.submission_revision.rubric_bank import RubricBank


class FeedbackPolicy(str, Enum):
    """Information from the optimizer judge that the solver may see."""

    FULL = "full"
    SEMI = "semi"
    SCORE_ONLY = "score_only"
    SIMULATED_USER = "simulated_user"


MAX_SIMULATED_USER_COMMENT_CHARS = 6_000


@dataclass(frozen=True)
class ProjectedFeedback:
    """Canonical feedback record and the corresponding solver message."""

    score: float
    payload: dict[str, object]
    prompt: str


@dataclass(frozen=True)
class _CriterionSummary:
    title: str
    maximum_points: int


_CRITERION_TITLE_PATTERN = re.compile(
    r"^[ \t]*Criterion[ \t]+(\d+)[ \t]*:[ \t]*(.*?)[ \t]*$",
    flags=re.MULTILINE,
)


def render_feedback_prompt(
    payload: dict[str, object],
    prompt_profile: PromptProfile | str = PromptProfile.BASE,
    benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
) -> str:
    """Render a canonical solver message from one projected feedback record."""

    policy = FeedbackPolicy(payload.get("policy"))
    resolved_profile = PromptProfile(prompt_profile)
    revision_action = get_submission_benchmark(benchmark).revision_action

    if policy is FeedbackPolicy.SIMULATED_USER:
        if set(payload) != {"policy", "comment", "bank_sha256"}:
            raise ValueError("simulated-user feedback contains unexpected fields")
        comment = payload.get("comment")
        if (
            type(comment) is not str
            or not comment.strip()
            or comment != comment.strip()
            or len(comment) > MAX_SIMULATED_USER_COMMENT_CHARS
        ):
            raise ValueError("simulated-user feedback contains an invalid comment")
        prompt = (
            "A user reviewed your previous submission and left this feedback:\n\n"
            "<user_feedback>\n"
            f"{comment}\n"
            "</user_feedback>\n\n"
            "Continue in the same workspace and revise the solution in response. "
            f"{revision_action} No score, rubric breakdown, "
            "or judge reasoning is available."
        )
        guidance = revision_guidance(resolved_profile)
        if guidance is not None:
            prompt += "\n\n" + guidance
        return prompt

    score = payload.get("score")
    if isinstance(score, bool) or not isinstance(score, Real):
        raise ValueError("feedback payload has an invalid score")
    score = float(score)
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("feedback score must be between 0 and 100")
    if policy is FeedbackPolicy.SCORE_ONLY:
        if set(payload) != {"policy", "score", "bank_sha256"}:
            raise ValueError("score-only feedback contains unexpected fields")
        prompt = (
            f"Your previous submission received a validated total score of "
            f"{score:g}/100. Continue in the same workspace and revise the "
            f"solution to improve it. {revision_action}"
        )
        guidance = revision_guidance(resolved_profile)
        if guidance is not None:
            prompt += "\n\n" + guidance
        return prompt

    if policy is FeedbackPolicy.SEMI:
        expected_keys = {
            "policy",
            "score",
            "bank_sha256",
            "members",
        }
        if set(payload) != expected_keys:
            raise ValueError("semi feedback contains unexpected fields")
        if type(payload.get("members")) is not dict:
            raise ValueError("semi feedback contains invalid fields")
        aggregate = _validate_bank_members(payload["members"], policy)
        if not math.isclose(score, aggregate, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("semi feedback score differs from member aggregate")
        prompt = (
            "Your previous submission received the validated score breakdown "
            "below. Continue in the same workspace and revise the solution to "
            "improve weak criteria. No judge reasoning is provided, so diagnose "
            "the causes from the task inputs and your own submission. "
            f"{revision_action}"
        )
        guidance = revision_guidance(resolved_profile)
        if guidance is not None:
            prompt += "\n\n" + guidance
        return prompt + "\n\n" + json.dumps(
            payload, ensure_ascii=False, indent=2, sort_keys=True
        )

    expected_keys = {
        "policy",
        "score",
        "bank_sha256",
        "members",
    }
    if set(payload) != expected_keys:
        raise ValueError("full feedback contains unexpected fields")
    if (
        type(payload.get("members")) is not dict
    ):
        raise ValueError("full feedback contains invalid fields")
    aggregate = _validate_bank_members(payload["members"], policy)
    if not math.isclose(score, aggregate, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("full feedback score differs from member aggregate")
    prompt = (
        "Continue in the same workspace and revise your current solution using "
        f"the feedback below. {revision_action} Judge "
        "reasons are model feedback, not verified evidence; check them against "
        "the task data and your artifacts."
    )
    guidance = revision_guidance(resolved_profile)
    if guidance is not None:
        prompt += "\n\n" + guidance
    return prompt + "\n\n" + json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    )


def _validate_bank_members(value: object, policy: FeedbackPolicy) -> float:
    if not isinstance(value, dict) or not value:
        raise ValueError("bank feedback must contain members")
    for rubric_hash, member in value.items():
        if (
            type(rubric_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", rubric_hash) is None
            or not isinstance(member, dict)
        ):
            raise ValueError("bank feedback contains an invalid member")
        expected = {"weight", "score", "raw_score", "criteria"}
        if policy is FeedbackPolicy.FULL:
            expected |= {"rubric_text", "overall_reasoning"}
        if set(member) != expected:
            raise ValueError("bank feedback contains invalid member fields")
        weight = member.get("weight")
        member_score = member.get("score")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, Real)
            or not math.isfinite(float(weight))
            or float(weight) <= 0
            or type(member_score) is not int
            or not 0 <= member_score <= 100
            or type(member.get("raw_score")) is not int
            or type(member.get("criteria")) is not dict
        ):
            raise ValueError("bank feedback contains invalid member values")
        if policy is FeedbackPolicy.FULL and (
            type(member.get("rubric_text")) is not str
            or type(member.get("overall_reasoning")) is not str
        ):
            raise ValueError("bank feedback contains invalid full member values")
    weights = [float(member["weight"]) for member in value.values()]
    if not math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("bank feedback member weights must sum to 1")
    return math.fsum(
        float(member["weight"]) * float(member["score"])
        for member in value.values()
    )


def project_bank_feedback(
    bank: RubricBank,
    artifacts: Mapping[str, tuple[Path, Path]],
    policy: FeedbackPolicy,
    *,
    max_reason_chars: int = 2_000,
    prompt_profile: PromptProfile | str = PromptProfile.BASE,
    benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
) -> ProjectedFeedback:
    """Project exact member evaluations and their weighted bank aggregate."""

    resolved_policy = FeedbackPolicy(policy)
    if resolved_policy is FeedbackPolicy.SIMULATED_USER:
        raise ValueError("use project_bank_simulated_user_feedback")
    expected_hashes = {item.rubric.content_sha256 for item in bank.items}
    if set(artifacts) != expected_hashes:
        raise ValueError("judge artifacts must match the rubric bank exactly")
    member_payloads: dict[str, dict[str, object]] = {}
    member_scores: dict[str, float] = {}
    for item in bank.items:
        rubric_hash = item.rubric.content_sha256
        validation_path, evaluation_path = artifacts[rubric_hash]
        projected = _project_member_feedback(
            validation_path,
            evaluation_path,
            item.rubric.content,
            rubric_hash,
            resolved_policy,
            max_reason_chars=max_reason_chars,
            prompt_profile=prompt_profile,
            benchmark=benchmark,
        )
        member_scores[rubric_hash] = projected.score
        if resolved_policy is not FeedbackPolicy.SCORE_ONLY:
            member = dict(projected.payload)
            member.pop("policy")
            member["weight"] = item.weight
            member_payloads[rubric_hash] = member
    score = bank.aggregate(member_scores)
    payload: dict[str, object] = {
        "policy": resolved_policy.value,
        "score": score,
        "bank_sha256": bank.content_sha256,
    }
    if resolved_policy is not FeedbackPolicy.SCORE_ONLY:
        payload["members"] = member_payloads
    return ProjectedFeedback(
        score=score,
        payload=payload,
        prompt=render_feedback_prompt(payload, prompt_profile, benchmark),
    )


def project_bank_simulated_user_feedback(
    bank: RubricBank,
    score_validation_paths: Mapping[str, Path],
    comment: str,
    *,
    prompt_profile: PromptProfile | str = PromptProfile.BASE,
    benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
) -> ProjectedFeedback:
    """Pair a sealed user comment with the weighted validated bank score."""

    expected_hashes = {item.rubric.content_sha256 for item in bank.items}
    if set(score_validation_paths) != expected_hashes:
        raise ValueError("score validations must match the rubric bank exactly")
    scores: dict[str, float] = {}
    for item in bank.items:
        validation = _load_object(
            score_validation_paths[item.rubric.content_sha256],
            "score validation",
        )
        score, _, _, _ = _validate_score_record(
            validation,
            item.rubric.content,
            item.rubric.content_sha256,
        )
        scores[item.rubric.content_sha256] = score
    score = bank.aggregate(scores)
    payload: dict[str, object] = {
        "policy": FeedbackPolicy.SIMULATED_USER.value,
        "comment": comment,
        "bank_sha256": bank.content_sha256,
    }
    return ProjectedFeedback(
        score=score,
        payload=payload,
        prompt=render_feedback_prompt(payload, prompt_profile, benchmark),
    )


def render_rubric_bank(bank: RubricBank) -> str:
    """Render a bank with explicit member hashes and weights."""

    parts = [f"Complete rubric bank: {bank.content_sha256}"]
    for index, item in enumerate(bank.items, start=1):
        parts.extend((
            "",
            f"Member {index}",
            f"Rubric SHA-256: {item.rubric.content_sha256}",
            f"Weight: {item.weight:.17g}",
            "",
            item.rubric.content.rstrip(),
        ))
    return "\n".join(parts) + "\n"


def _project_member_feedback(
    score_validation_path: Path,
    evaluation_path: Path,
    rubric_text: str,
    expected_rubric_sha256: str,
    policy: FeedbackPolicy,
    max_reason_chars: int = 2_000,
    prompt_profile: PromptProfile | str = PromptProfile.BASE,
    benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
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

    if resolved_policy is FeedbackPolicy.SIMULATED_USER:
        raise ValueError(
            "simulated_user feedback must be projected from a persisted LLM comment"
        )

    if resolved_policy is FeedbackPolicy.SCORE_ONLY:
        payload: dict[str, object] = {
            "policy": resolved_policy.value,
            "score": score,
        }
        return ProjectedFeedback(score=score, payload=payload, prompt="")

    if resolved_policy is FeedbackPolicy.SEMI:
        rubric_levels = parse_rubric_levels_strict(rubric_text)
        summaries = _validated_criterion_summaries(
            rubric_text,
            rubric_levels,
            selected_levels,
            criterion_scores,
        )
        payload = {
            "policy": resolved_policy.value,
            "score": score,
            "raw_score": raw_score,
            "criteria": {
                criterion_id: {
                    "title": summaries[criterion_id].title,
                    "selected_level": selected_levels[criterion_id],
                    "points": criterion_scores[criterion_id],
                    "maximum_points": summaries[criterion_id].maximum_points,
                }
                for criterion_id in sorted(selected_levels)
            },
        }
        return ProjectedFeedback(score=score, payload=payload, prompt="")

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
    return ProjectedFeedback(score=score, payload=payload, prompt="")


def _criterion_summaries(
    rubric_text: str,
    rubric_levels: dict[str, dict[str, int]],
) -> dict[str, _CriterionSummary]:
    summaries: dict[str, _CriterionSummary] = {}
    for match in _CRITERION_TITLE_PATTERN.finditer(rubric_text):
        criterion_id = f"criterion_{match.group(1)}"
        title = match.group(2)
        if not title:
            raise ValueError(f"{criterion_id} must have a non-empty title")
        if criterion_id in summaries:
            raise ValueError(f"rubric contains duplicate criterion: {criterion_id}")
        levels = rubric_levels.get(criterion_id)
        if levels is None:
            raise ValueError(f"criterion title has no levels: {criterion_id}")
        summaries[criterion_id] = _CriterionSummary(title, max(levels.values()))
    if set(summaries) != set(rubric_levels):
        missing = sorted(set(rubric_levels) - set(summaries))
        raise ValueError(
            "rubric criteria lack parseable non-empty titles: " + ", ".join(missing)
        )
    return summaries


def _validated_criterion_summaries(
    rubric_text: str,
    rubric_levels: dict[str, dict[str, int]],
    selected_levels: dict[str, str],
    criterion_scores: dict[str, int],
) -> dict[str, _CriterionSummary]:
    summaries = _criterion_summaries(rubric_text, rubric_levels)
    if set(summaries) != set(selected_levels) or set(rubric_levels) != set(
        selected_levels
    ):
        raise ValueError(
            "rubric criterion summaries do not match validated score criteria"
        )
    for criterion_id, selected_level in selected_levels.items():
        if rubric_levels[criterion_id].get(selected_level) != criterion_scores[
            criterion_id
        ]:
            raise ValueError(
                "validated criterion score does not match the frozen rubric: "
                f"{criterion_id}"
            )
    return summaries


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
    normalized_score = validation.get("normalized_score")
    if type(normalized_score) is not float or not 0.0 <= normalized_score <= 1.0:
        raise ValueError("score validation normalized_score must be between zero and one")
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
    normalization_maximum = parse_score_normalization_maximum(rubric_text)
    expected_score = (
        round(raw_score * 100 / normalization_maximum)
        if normalization_maximum is not None
        else raw_score
    )
    if score != max(0, min(100, expected_score)):
        raise ValueError("score validation score does not match raw_score")
    expected_normalized_score = max(
        0.0,
        min(
            1.0,
            raw_score / (normalization_maximum or 100),
        ),
    )
    if normalized_score != expected_normalized_score:
        raise ValueError("score validation normalized_score does not match raw_score")
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
