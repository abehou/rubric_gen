"""Strictly parse rubric levels and recompute judge scores."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from numbers import Real



class JudgeScoreValidationError(ValueError):
    """Raised when rubric or judge score data is not structurally valid."""


@dataclass(frozen=True)
class ValidatedJudgeScore:
    score: float
    normalized_score: float
    raw_score: float
    reported_score: float
    score_matches_reported: bool
    criterion_levels: dict[str, str]
    criterion_scores: dict[str, float]


_CRITERION_PATTERN = re.compile(
    r"^[ \t]*Criterion[ \t]+(\d+)[ \t]*:",
    flags=re.MULTILINE,
)
_CRITERION_CANDIDATE_PATTERN = re.compile(r"^[ \t]*Criterion(?:[ \t]+\d+\b|[ \t]*$)")
_LEVELS_LINE_PATTERN = re.compile(
    r"^[ \t]*Levels:[ \t]*(.*?)[ \t]*$",
    flags=re.MULTILINE,
)
_LEVELS_VALUE_PATTERN = re.compile(r"[A-Z]=[+-]?\d+(?:[ \t]+[A-Z]=[+-]?\d+)*")
_LEVEL_PATTERN = re.compile(r"([A-Z])=([+-]?\d+)")
_NORMALIZATION_PATTERN = re.compile(
    r"^[ \t]*Score normalization maximum:[ \t]*([1-9]\d*)[ \t]*$",
    flags=re.MULTILINE,
)


def parse_score_normalization_maximum(rubric_text: str) -> int | None:
    """Return the optional raw-point maximum that maps to a score of 100."""

    matches = _NORMALIZATION_PATTERN.findall(rubric_text)
    if len(matches) > 1:
        raise JudgeScoreValidationError(
            "rubric contains more than one score normalization directive"
        )
    return int(matches[0]) if matches else None


def parse_rubric_levels_strict(rubric_text: str) -> dict[str, dict[str, int]]:
    """Parse every criterion's signed level values or reject the rubric."""

    if type(rubric_text) is not str or not rubric_text.strip():
        raise JudgeScoreValidationError("rubric must be a non-empty string")

    inside_recognized_criterion = False
    for line_number, line in enumerate(rubric_text.splitlines(), start=1):
        if _CRITERION_CANDIDATE_PATTERN.match(line) is not None:
            if _CRITERION_PATTERN.match(line) is None:
                raise JudgeScoreValidationError(
                    f"rubric has a malformed Criterion line at line {line_number}"
                )
            inside_recognized_criterion = True
        if (
            _LEVELS_LINE_PATTERN.match(line) is not None
            and not inside_recognized_criterion
        ):
            raise JudgeScoreValidationError(
                f"rubric has a Levels line outside a criterion at line {line_number}"
            )

    headers = list(_CRITERION_PATTERN.finditer(rubric_text))
    if not headers:
        raise JudgeScoreValidationError("rubric must contain at least one criterion")

    rubric_levels: dict[str, dict[str, int]] = {}
    for index, header in enumerate(headers):
        criterion_key = f"criterion_{header.group(1)}"
        if criterion_key in rubric_levels:
            raise JudgeScoreValidationError(
                f"rubric contains duplicate criterion: {criterion_key}"
            )

        body_end = (
            headers[index + 1].start() if index + 1 < len(headers) else len(rubric_text)
        )
        body = rubric_text[header.end() : body_end]
        levels_lines = list(_LEVELS_LINE_PATTERN.finditer(body))
        if len(levels_lines) != 1:
            raise JudgeScoreValidationError(
                f"{criterion_key} must contain exactly one Levels line"
            )

        levels_text = levels_lines[0].group(1)
        if _LEVELS_VALUE_PATTERN.fullmatch(levels_text) is None:
            raise JudgeScoreValidationError(
                f"{criterion_key} has a malformed Levels line"
            )

        levels: dict[str, int] = {}
        for level_match in _LEVEL_PATTERN.finditer(levels_text):
            label = level_match.group(1)
            if label in levels:
                raise JudgeScoreValidationError(
                    f"{criterion_key} contains duplicate level: {label}"
                )
            levels[label] = int(level_match.group(2))
        rubric_levels[criterion_key] = levels

    return rubric_levels


def validate_judge_score(
    *,
    rubric_levels: object,
    evaluation: object,
    reward: object,
    normalization_maximum: int | None = None,
) -> ValidatedJudgeScore:
    """Validate judge artifacts and authoritatively recompute the signed score."""

    levels_by_criterion = _validate_rubric_levels(rubric_levels)
    if type(evaluation) is not dict:
        raise JudgeScoreValidationError("evaluation must be an object")
    if "criteria" not in evaluation or type(evaluation["criteria"]) is not dict:
        raise JudgeScoreValidationError("evaluation.criteria must be an object")
    criteria = evaluation["criteria"]
    if set(criteria) != set(levels_by_criterion):
        raise JudgeScoreValidationError(
            "evaluation criterion keys must exactly match rubric criterion keys"
        )

    if type(reward) is not dict or set(reward) != {"score"}:
        raise JudgeScoreValidationError(
            "reward must be an object with exactly one score key"
        )
    reported_score = reward["score"]
    if (
        isinstance(reported_score, bool)
        or not isinstance(reported_score, Real)
        or not math.isfinite(float(reported_score))
    ):
        raise JudgeScoreValidationError("reward.score must be a finite number")
    reported_score = float(reported_score)
    if not 0.0 <= reported_score <= 100.0:
        raise JudgeScoreValidationError("reward.score must be between 0 and 100")

    criterion_levels: dict[str, str] = {}
    criterion_scores: dict[str, float] = {}
    for criterion_key, levels in levels_by_criterion.items():
        criterion = criteria[criterion_key]
        if type(criterion) is not dict:
            raise JudgeScoreValidationError(
                f"evaluation.criteria.{criterion_key} must be an object"
            )
        level = criterion.get("level")
        if type(level) is not str:
            raise JudgeScoreValidationError(
                f"evaluation.criteria.{criterion_key}.level must be a string"
            )
        if level not in levels:
            raise JudgeScoreValidationError(
                f"evaluation.criteria.{criterion_key}.level is not in the rubric"
            )
        points = levels[level]
        reported_points = criterion.get("points")
        if (
            isinstance(reported_points, bool)
            or not isinstance(reported_points, Real)
            or not math.isfinite(float(reported_points))
            or not math.isclose(
                float(reported_points),
                points,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise JudgeScoreValidationError(
                f"evaluation.criteria.{criterion_key}.points does not match its level"
            )
        criterion_levels[criterion_key] = level
        criterion_scores[criterion_key] = float(points)

    if normalization_maximum is not None and (
        type(normalization_maximum) is not int or normalization_maximum < 1
    ):
        raise JudgeScoreValidationError(
            "score normalization maximum must be a positive integer"
        )
    denominator = normalization_maximum or 100
    raw_score = math.fsum(criterion_scores.values())
    score = max(0.0, min(100.0, raw_score * 100 / denominator))
    normalized_score = score / 100
    return ValidatedJudgeScore(
        score=score,
        normalized_score=normalized_score,
        raw_score=raw_score,
        reported_score=reported_score,
        score_matches_reported=math.isclose(
            score, reported_score, rel_tol=0.0, abs_tol=1e-12
        ),
        criterion_levels=criterion_levels,
        criterion_scores=criterion_scores,
    )


def _validate_rubric_levels(value: object) -> dict[str, dict[str, int]]:
    if type(value) is not dict or not value:
        raise JudgeScoreValidationError("rubric_levels must be a non-empty object")

    validated: dict[str, dict[str, int]] = {}
    for criterion_key, raw_levels in value.items():
        if (
            type(criterion_key) is not str
            or type(raw_levels) is not dict
            or not raw_levels
        ):
            raise JudgeScoreValidationError("rubric_levels has an invalid criterion")
        levels: dict[str, int] = {}
        for label, points in raw_levels.items():
            if type(label) is not str or type(points) is not int:
                raise JudgeScoreValidationError(
                    f"rubric_levels.{criterion_key} has an invalid level"
                )
            levels[label] = points
        validated[criterion_key] = levels
    return validated
