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
from rubric_gen.submission_revision.judging.models import JUDGMENT_REPEATS
from rubric_gen.submission_revision.rubrics.schema import load_json_strict
from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.submission_revision.rubric_bank import (
    RubricBank,
    canonical_rubric_bank_items,
)


class FeedbackPolicy(str, Enum):
    """Information from the optimizer judge that the solver may see."""

    FULL = "full"
    SEMI = "semi"
    SCORE_ONLY = "score_only"
    USER_SIMULATOR = "user_simulator"


MAX_SIMULATED_USER_COMMENT_CHARS = 6_000


@dataclass(frozen=True)
class ProjectedFeedback:
    """Canonical feedback record and the corresponding solver message."""

    score: float
    payload: dict[str, object]
    prompt: str


@dataclass(frozen=True)
class ComposedMemberScore:
    """Store one member's canonical base, learned penalty, and final score."""

    canonical_original_score: float
    elicited_penalty: float
    score: float


@dataclass(frozen=True)
class ComposedBankScore:
    """Store the canonical-base score composition for one rubric bank."""

    canonical_original_score: float
    weighted_elicited_penalty: float
    score: float
    members: dict[str, ComposedMemberScore]


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

    if policy is FeedbackPolicy.USER_SIMULATOR:
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
        expected = {
            "weight",
            "score",
            "canonical_original_score",
            "elicited_penalty",
            "criteria",
        }
        if policy is FeedbackPolicy.FULL:
            expected |= {"rubric_text", "overall_reasoning"}
        if set(member) != expected:
            raise ValueError("bank feedback contains invalid member fields")
        weight = member.get("weight")
        member_score = member.get("score")
        canonical_original_score = member.get("canonical_original_score")
        elicited_penalty = member.get("elicited_penalty")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, Real)
            or not math.isfinite(float(weight))
            or float(weight) <= 0
            or isinstance(member_score, bool)
            or not isinstance(member_score, Real)
            or not math.isfinite(float(member_score))
            or not 0 <= float(member_score) <= 100
            or isinstance(canonical_original_score, bool)
            or not isinstance(canonical_original_score, Real)
            or not math.isfinite(float(canonical_original_score))
            or not 0 <= float(canonical_original_score) <= 100
            or isinstance(elicited_penalty, bool)
            or not isinstance(elicited_penalty, Real)
            or not math.isfinite(float(elicited_penalty))
            or float(elicited_penalty) > 0
            or not math.isclose(
                float(member_score),
                max(
                    0.0,
                    float(canonical_original_score) + float(elicited_penalty),
                ),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
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
    fixed_original_artifacts: tuple[Path, Path],
    fixed_original_rubric_text: str,
    fixed_original_rubric_sha256: str,
    max_reason_chars: int = 2_000,
    prompt_profile: PromptProfile | str = PromptProfile.BASE,
    benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
) -> ProjectedFeedback:
    """Project canonical original feedback plus learned-criterion penalties."""

    resolved_policy = FeedbackPolicy(policy)
    if resolved_policy is FeedbackPolicy.USER_SIMULATOR:
        raise ValueError("use project_bank_simulated_user_feedback")
    expected_hashes = {item.rubric.content_sha256 for item in bank.items}
    if set(artifacts) != expected_hashes:
        raise ValueError("judge artifacts must match the rubric bank exactly")
    composition = compose_bank_score(
        bank,
        {
            rubric_hash: paths[0]
            for rubric_hash, paths in artifacts.items()
        },
        _validated_fixed_original_score(
            fixed_original_artifacts[0],
            fixed_original_rubric_text,
            fixed_original_rubric_sha256,
        ),
    )
    if resolved_policy is FeedbackPolicy.SCORE_ONLY:
        payload = {
            "policy": resolved_policy.value,
            "score": composition.score,
            "bank_sha256": bank.content_sha256,
        }
        return ProjectedFeedback(
            score=composition.score,
            payload=payload,
            prompt=render_feedback_prompt(payload, prompt_profile, benchmark),
        )

    fixed_projection = _project_member_feedback(
        fixed_original_artifacts[0],
        fixed_original_artifacts[1],
        fixed_original_rubric_text,
        fixed_original_rubric_sha256,
        resolved_policy,
        max_reason_chars=max_reason_chars,
        prompt_profile=prompt_profile,
        benchmark=benchmark,
    )
    fixed_criteria = fixed_projection.payload.get("criteria")
    if not isinstance(fixed_criteria, dict):
        raise ValueError("fixed-original feedback lacks criterion details")
    member_payloads: dict[str, dict[str, object]] = {}
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
        active_criteria = projected.payload.get("criteria")
        if not isinstance(active_criteria, dict):
            raise ValueError("active feedback lacks criterion details")
        merged_criteria: dict[str, object] = {}
        original_member_ids: set[str] = set()
        for mapping in item.criterion_map:
            fixed_criterion = fixed_criteria.get(mapping.anchor_criterion_id)
            if not isinstance(fixed_criterion, dict):
                raise ValueError("fixed-original criterion mapping is incomplete")
            if mapping.member_criterion_id not in active_criteria:
                raise ValueError("active criterion mapping is incomplete")
            merged_criteria[mapping.member_criterion_id] = fixed_criterion
            original_member_ids.add(mapping.member_criterion_id)
        elicited_ids = set(active_criteria) - original_member_ids
        if len(elicited_ids) != len(item.elicited_criteria):
            raise ValueError("active feedback has the wrong elicited criteria")
        for criterion_id in sorted(elicited_ids):
            merged_criteria[criterion_id] = active_criteria[criterion_id]

        member_composition = composition.members[rubric_hash]
        member: dict[str, object] = {
            "weight": item.weight,
            "score": member_composition.score,
            "canonical_original_score": (
                member_composition.canonical_original_score
            ),
            "elicited_penalty": member_composition.elicited_penalty,
            "criteria": merged_criteria,
        }
        if resolved_policy is FeedbackPolicy.FULL:
            member["rubric_text"] = item.rubric.content
            member["overall_reasoning"] = fixed_projection.payload[
                "overall_reasoning"
            ]
        member_payloads[rubric_hash] = member
    payload: dict[str, object] = {
        "policy": resolved_policy.value,
        "score": composition.score,
        "bank_sha256": bank.content_sha256,
        "members": member_payloads,
    }
    return ProjectedFeedback(
        score=composition.score,
        payload=payload,
        prompt=render_feedback_prompt(payload, prompt_profile, benchmark),
    )


def project_bank_simulated_user_feedback(
    bank: RubricBank,
    score_validation_paths: Mapping[str, Path],
    comment: str,
    *,
    fixed_original_score: float,
    prompt_profile: PromptProfile | str = PromptProfile.BASE,
    benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
) -> ProjectedFeedback:
    """Pair a sealed user comment with the weighted validated bank score."""

    expected_hashes = {item.rubric.content_sha256 for item in bank.items}
    if set(score_validation_paths) != expected_hashes:
        raise ValueError("score validations must match the rubric bank exactly")
    composition = compose_bank_score(
        bank,
        score_validation_paths,
        fixed_original_score,
    )
    payload: dict[str, object] = {
        "policy": FeedbackPolicy.USER_SIMULATOR.value,
        "comment": comment,
        "bank_sha256": bank.content_sha256,
    }
    return ProjectedFeedback(
        score=composition.score,
        payload=payload,
        prompt=render_feedback_prompt(payload, prompt_profile, benchmark),
    )


def compose_bank_score(
    bank: RubricBank,
    score_validation_paths: Mapping[str, Path],
    fixed_original_score: float,
) -> ComposedBankScore:
    """Add only elicited penalties to one canonical original score."""

    if (
        isinstance(fixed_original_score, bool)
        or not isinstance(fixed_original_score, Real)
        or not math.isfinite(float(fixed_original_score))
        or not 0 <= float(fixed_original_score) <= 100
    ):
        raise ValueError("fixed_original_score must be between zero and 100")
    fixed = float(fixed_original_score)
    expected_hashes = {item.rubric.content_sha256 for item in bank.items}
    if set(score_validation_paths) != expected_hashes:
        raise ValueError("score validations must match the rubric bank exactly")

    member_compositions: dict[str, ComposedMemberScore] = {}
    member_scores: dict[str, float] = {}
    member_penalties: dict[str, float] = {}
    for item in bank.items:
        rubric_hash = item.rubric.content_sha256
        validation = _load_object(
            score_validation_paths[rubric_hash],
            "score validation",
        )
        _, _, _, criterion_scores = _validate_score_record(
            validation,
            item.rubric.content,
            rubric_hash,
        )
        original_ids = {
            mapping.member_criterion_id for mapping in item.criterion_map
        }
        if not original_ids <= set(criterion_scores):
            raise ValueError("score validation lacks mapped original criteria")
        elicited_ids = set(criterion_scores) - original_ids
        if len(elicited_ids) != len(item.elicited_criteria):
            raise ValueError("score validation has the wrong elicited criteria")
        elicited_raw_penalty = math.fsum(
            criterion_scores[criterion_id]
            for criterion_id in elicited_ids
        )
        if elicited_raw_penalty > 1e-12:
            raise ValueError("elicited criteria produced a positive score")
        penalty = elicited_raw_penalty * 100 / bank.normalization_maximum
        score = max(0.0, fixed + penalty)
        member_compositions[rubric_hash] = ComposedMemberScore(
            canonical_original_score=fixed,
            elicited_penalty=penalty,
            score=score,
        )
        member_scores[rubric_hash] = score
        member_penalties[rubric_hash] = penalty

    return ComposedBankScore(
        canonical_original_score=fixed,
        weighted_elicited_penalty=bank.aggregate(member_penalties),
        score=bank.aggregate(member_scores),
        members=member_compositions,
    )


def _validated_fixed_original_score(
    validation_path: Path,
    rubric_text: str,
    rubric_sha256: str,
) -> float:
    validation = _load_object(validation_path, "fixed-original score validation")
    score, _, _, _ = _validate_score_record(
        validation,
        rubric_text,
        rubric_sha256,
    )
    return score


def render_rubric_bank(bank: RubricBank) -> str:
    """Render a bank with explicit member hashes and weights."""

    parts = [f"Complete rubric bank: {bank.content_sha256}"]
    for index, item in enumerate(canonical_rubric_bank_items(bank), start=1):
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
    score, raw_score, criterion_level_votes, criterion_scores = _validate_score_record(
        validation,
        rubric_text,
        expected_rubric_sha256,
    )

    try:
        resolved_policy = FeedbackPolicy(policy)
    except ValueError as exc:
        raise ValueError(f"unsupported feedback policy: {policy}") from exc

    if resolved_policy is FeedbackPolicy.USER_SIMULATOR:
        raise ValueError(
            "user_simulator feedback must be projected from a persisted LLM comment"
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
            criterion_level_votes,
            criterion_scores,
        )
        payload = {
            "policy": resolved_policy.value,
            "score": score,
            "raw_score": raw_score,
            "criteria": {
                criterion_id: {
                    "title": summaries[criterion_id].title,
                    "level_votes": list(criterion_level_votes[criterion_id]),
                    "mean_points": criterion_scores[criterion_id],
                    "maximum_points": summaries[criterion_id].maximum_points,
                }
                for criterion_id in sorted(criterion_level_votes)
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
        criterion_level_votes=criterion_level_votes,
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
    criterion_level_votes: dict[str, tuple[str, ...]],
    criterion_scores: dict[str, float],
) -> dict[str, _CriterionSummary]:
    summaries = _criterion_summaries(rubric_text, rubric_levels)
    if set(summaries) != set(criterion_level_votes) or set(rubric_levels) != set(
        criterion_level_votes
    ):
        raise ValueError(
            "rubric criterion summaries do not match validated score criteria"
        )
    for criterion_id, level_votes in criterion_level_votes.items():
        expected_mean = (
            math.fsum(rubric_levels[criterion_id][level] for level in level_votes)
            / JUDGMENT_REPEATS
        )
        if not math.isclose(
            expected_mean,
            criterion_scores[criterion_id],
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "validated criterion mean does not match the frozen rubric: "
                f"{criterion_id}"
            )
    return summaries


def _validate_score_record(
    validation: dict[str, object],
    rubric_text: str,
    expected_rubric_sha256: str,
) -> tuple[float, float, dict[str, tuple[str, ...]], dict[str, float]]:
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

    score = _finite_number(validation, "score")
    raw_score = _finite_number(validation, "raw_score")
    normalized_score = validation.get("normalized_score")
    if type(normalized_score) is not float or not 0.0 <= normalized_score <= 1.0:
        raise ValueError("score validation normalized_score must be between zero and one")
    if not 0 <= score <= 100:
        raise ValueError("score validation score must be between 0 and 100")
    criterion_level_votes = _level_vote_map(
        validation, "criterion_level_votes"
    )
    criterion_scores = _number_map(validation, "criterion_scores")
    if set(criterion_level_votes) != set(criterion_scores):
        raise ValueError(
            "score validation criterion_level_votes and criterion_scores must have "
            "the same criteria"
        )
    if not math.isclose(
        raw_score,
        math.fsum(criterion_scores.values()),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("score validation raw_score does not match criterion scores")
    rubric_levels = parse_rubric_levels_strict(rubric_text)
    if set(rubric_levels) != set(criterion_level_votes):
        raise ValueError("score validation criteria do not match the frozen rubric")
    repeat_raw_scores = [
        math.fsum(
            rubric_levels[criterion_id][
                criterion_level_votes[criterion_id][repeat_index]
            ]
            for criterion_id in rubric_levels
        )
        for repeat_index in range(JUDGMENT_REPEATS)
    ]
    normalization_maximum = parse_score_normalization_maximum(rubric_text)
    expected_repeat_scores = (
        max(
            0.0,
            min(100.0, repeat_raw * 100 / (normalization_maximum or 100)),
        )
        for repeat_raw in repeat_raw_scores
    )
    expected_score = math.fsum(expected_repeat_scores) / JUDGMENT_REPEATS
    if not math.isclose(score, expected_score, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("score validation score does not match level votes")
    expected_normalized_score = expected_score / 100
    if not math.isclose(
        normalized_score,
        expected_normalized_score,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError(
            "score validation normalized_score does not match level votes"
        )
    return score, raw_score, criterion_level_votes, criterion_scores


def _project_full_payload(
    *,
    validation: dict[str, object],
    evaluation_path: Path,
    rubric_text: str,
    score: float,
    raw_score: float,
    criterion_level_votes: dict[str, tuple[str, ...]],
    criterion_scores: dict[str, float],
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
    for criterion_id in sorted(criterion_level_votes):
        evaluation_criterion = evaluation_criteria.get(criterion_id)
        reason = (
            evaluation_criterion.get("reason", "")
            if type(evaluation_criterion) is dict
            else ""
        )
        criteria[criterion_id] = {
            "level_votes": list(criterion_level_votes[criterion_id]),
            "mean_points": criterion_scores[criterion_id],
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


def _finite_number(payload: dict[str, object], key: str) -> float:
    value = payload.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"score validation {key} must be a finite number")
    return float(value)


def _level_vote_map(
    payload: dict[str, object], key: str
) -> dict[str, tuple[str, ...]]:
    value = payload.get(key)
    if type(value) is not dict or not value:
        raise ValueError(f"score validation {key} must be a non-empty object")
    result: dict[str, tuple[str, ...]] = {}
    for item_key, item_value in value.items():
        if (
            type(item_key) is not str
            or not item_key
            or type(item_value) is not list
            or len(item_value) != JUDGMENT_REPEATS
            or any(type(level) is not str or not level for level in item_value)
        ):
            raise ValueError(f"score validation {key} has an invalid entry")
        result[item_key] = tuple(item_value)
    return result


def _number_map(payload: dict[str, object], key: str) -> dict[str, float]:
    value = payload.get(key)
    if type(value) is not dict or not value:
        raise ValueError(f"score validation {key} must be a non-empty object")
    result: dict[str, float] = {}
    for item_key, item_value in value.items():
        if (
            type(item_key) is not str
            or not item_key
            or isinstance(item_value, bool)
            or not isinstance(item_value, Real)
            or not math.isfinite(float(item_value))
        ):
            raise ValueError(f"score validation {key} has an invalid entry")
        result[item_key] = float(item_value)
    return result


def _bounded_text(value: object, max_chars: int) -> str:
    return value[:max_chars] if type(value) is str else ""
