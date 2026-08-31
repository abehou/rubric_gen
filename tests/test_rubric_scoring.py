from __future__ import annotations

import pytest

from rubric_gen.submission_revision.judging.scoring import (
    JudgeScoreValidationError,
    parse_rubric_levels_strict,
    validate_judge_score,
)


RUBRIC = (
    "Criterion 1: Work\n"
    "Levels: A=100 B=50 C=0\n"
    "Criterion 2: Integrity\n"
    "Levels: A=0 B=-5 C=-10\n"
)


def test_recomputation_applies_penalty() -> None:
    levels = parse_rubric_levels_strict(RUBRIC)

    result = validate_judge_score(
        rubric_levels=levels,
        evaluation={
            "criteria": {
                "criterion_1": {
                    "level": "B",
                    "points": 50,
                },
                "criterion_2": {
                    "level": "C",
                    "points": -10,
                },
            }
        },
        reward={"score": 50.0},
    )

    assert (result.raw_score, result.score) == (40.0, 40.0)
    assert result.normalized_score == 0.4
    assert result.reported_score == 50.0
    assert not result.score_matches_reported
    assert result.criterion_levels == {
        "criterion_1": "B",
        "criterion_2": "C",
    }
    assert result.criterion_scores == {"criterion_1": 50.0, "criterion_2": -10.0}


def test_score_uses_the_selected_level() -> None:
    result = validate_judge_score(
        rubric_levels={"criterion_1": {"A": 2, "B": 0}},
        evaluation={
            "criteria": {
                "criterion_1": {
                    "level": "A",
                    "points": 2,
                }
            }
        },
        reward={"score": 2.0},
    )

    assert result.score == 2.0
    assert result.raw_score == 2.0
    assert result.normalized_score == 0.02
    assert result.score_matches_reported


def test_raw_score_uses_the_criterion_sum() -> None:
    result = validate_judge_score(
        rubric_levels={
            "criterion_1": {"A": 1_000_001, "B": 0},
            "criterion_2": {"A": 0, "B": -1_000_001},
        },
        evaluation={
            "criteria": {
                "criterion_1": {
                    "level": "A",
                    "points": 1_000_001,
                },
                "criterion_2": {
                    "level": "B",
                    "points": -1_000_001,
                },
            }
        },
        reward={"score": 0.0},
    )

    assert result.raw_score == 0


def test_parser_preserves_explicit_positive_and_negative_values() -> None:
    levels = parse_rubric_levels_strict(
        "Criterion 1: Signed\nLevels: A=+10 B=0 C=-10\n"
    )

    assert levels == {"criterion_1": {"A": 10, "B": 0, "C": -10}}


def test_parser_allows_criterion_prefixed_prose() -> None:
    rubric = (
        "Criterion-based scoring is explained below.\n"
        "Criterion 1: Valid\n"
        "Levels: A=10 B=0\n"
    )

    assert parse_rubric_levels_strict(rubric) == {"criterion_1": {"A": 10, "B": 0}}


def test_parser_allows_levels_prefixed_prose() -> None:
    rubric = (
        "Levels-based guidance is explained below.\n"
        "Criterion 1: Valid\n"
        "Levels: A=10 B=0\n"
    )

    assert parse_rubric_levels_strict(rubric) == {"criterion_1": {"A": 10, "B": 0}}


def test_parser_rejects_unparseable_criterion_candidate_line() -> None:
    rubric = "Criterion 2 missing colon\nCriterion 1: Valid\nLevels: A=10 B=0\n"

    with pytest.raises(JudgeScoreValidationError):
        parse_rubric_levels_strict(rubric)


def test_parser_rejects_levels_line_before_first_criterion() -> None:
    rubric = "Levels: A=999 B=0\nCriterion 1: Valid\nLevels: A=10 B=0\n"

    with pytest.raises(JudgeScoreValidationError):
        parse_rubric_levels_strict(rubric)


@pytest.mark.parametrize(
    "rubric",
    (
        "Criterion 1: First\nLevels: A=1 B=0\n"
        "Criterion 1: Duplicate\nLevels: A=1 B=0\n",
        "Criterion 1: Duplicate level\nLevels: A=1 A=0\n",
        "Criterion 1: Duplicate line\nLevels: A=1 B=0\nLevels: A=1 B=0\n",
    ),
)
def test_parser_rejects_duplicate_criteria_or_levels(rubric: str) -> None:
    with pytest.raises(JudgeScoreValidationError):
        parse_rubric_levels_strict(rubric)


@pytest.mark.parametrize(
    "rubric",
    (
        "",
        "   \n",
        "Purpose: no criteria\n",
        "Criterion 1: Missing levels\nDescription: none\n",
        "Criterion 1: Empty levels\nLevels:\n",
        "Criterion 1: Malformed levels\nLevels: A=10 B=nope C=0\n",
    ),
)
def test_parser_rejects_empty_or_incomplete_rubrics(rubric: str) -> None:
    with pytest.raises(JudgeScoreValidationError):
        parse_rubric_levels_strict(rubric)


@pytest.mark.parametrize(
    "criteria",
    (
        {"criterion_1": {"level": "A", "points": 100.0}},
        {
            "criterion_1": {"level": "A", "points": 100.0},
            "criterion_2": {"level": "A", "points": 0.0},
            "criterion_3": {"level": "A", "points": 0.0},
        },
    ),
)
def test_evaluation_criterion_keys_must_equal_rubric_keys(
    criteria: dict[str, object],
) -> None:
    with pytest.raises(JudgeScoreValidationError):
        validate_judge_score(
            rubric_levels=parse_rubric_levels_strict(RUBRIC),
            evaluation={"criteria": criteria},
            reward={"score": 100.0},
        )


@pytest.mark.parametrize("level", ("D", "b", " B "))
def test_unknown_or_inexact_level_vote_is_rejected(level: str) -> None:
    with pytest.raises(JudgeScoreValidationError):
        validate_judge_score(
            rubric_levels={"criterion_1": {"A": 10, "B": 0}},
            evaluation={"criteria": {"criterion_1": {
                "level": level,
                "points": 0.0,
            }}},
            reward={"score": 0.0},
        )


@pytest.mark.parametrize("level", (None, 1, True, 1.0))
def test_non_string_level_vote_is_rejected(level: object) -> None:
    with pytest.raises(JudgeScoreValidationError):
        validate_judge_score(
            rubric_levels={"criterion_1": {"A": 10, "B": 0}},
            evaluation={"criteria": {"criterion_1": {
                "level": level,
                "points": 0.0,
            }}},
            reward={"score": 0.0},
        )


@pytest.mark.parametrize("reported_score", (True, "50", float("nan"), -1, 101))
def test_reward_score_requires_an_in_range_finite_number(
    reported_score: object,
) -> None:
    with pytest.raises(JudgeScoreValidationError):
        validate_judge_score(
            rubric_levels={"criterion_1": {"A": 50}},
            evaluation={"criteria": {"criterion_1": {
                "level": "A",
                "points": 50.0,
            }}},
            reward={"score": reported_score},
        )


@pytest.mark.parametrize(
    "reward",
    ({}, {"score": 50.0, "extra": 0}, [], None),
)
def test_reward_must_be_an_object_with_exactly_one_score_key(
    reward: object,
) -> None:
    with pytest.raises(JudgeScoreValidationError):
        validate_judge_score(
            rubric_levels={"criterion_1": {"A": 50}},
            evaluation={"criteria": {"criterion_1": {
                "level": "A",
                "points": 50.0,
            }}},
            reward=reward,
        )


@pytest.mark.parametrize(
    ("rubric", "reported_score", "expected_raw", "expected_score"),
    (
        ("Criterion 1: Penalty\nLevels: A=-20\n", 0.0, -20.0, 0.0),
        ("Criterion 1: Bonus\nLevels: A=120\n", 100.0, 120.0, 100.0),
    ),
)
def test_authoritative_score_is_clamped_but_raw_score_is_preserved(
    rubric: str,
    reported_score: float,
    expected_raw: float,
    expected_score: float,
) -> None:
    result = validate_judge_score(
        rubric_levels=parse_rubric_levels_strict(rubric),
        evaluation={"criteria": {"criterion_1": {
            "level": "A",
            "points": expected_raw,
        }}},
        reward={"score": reported_score},
    )

    assert result.raw_score == expected_raw
    assert result.score == expected_score
    assert result.score_matches_reported


@pytest.mark.parametrize(
    "evaluation",
    (
        None,
        [],
        {},
        {"criteria": []},
        {"criteria": {"criterion_1": "A"}},
        {"criteria": {"criterion_1": {}}},
    ),
)
def test_malformed_evaluation_fails_closed(evaluation: object) -> None:
    with pytest.raises(JudgeScoreValidationError):
        validate_judge_score(
            rubric_levels={"criterion_1": {"A": 10}},
            evaluation=evaluation,
            reward={"score": 10.0},
        )
