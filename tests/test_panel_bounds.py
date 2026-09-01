from __future__ import annotations

import pytest

from rubric_gen.submission_revision.evaluation.panel_bounds import (
    detection_bounds,
    paired_effect_bounds,
)


@pytest.mark.parametrize(
    ("rule", "decisions", "expected"),
    (
        (
            "any_detect",
            {"a": "detected", "b": "not_detected"},
            (1, 1),
        ),
        (
            "any_detect",
            {"a": "not_detected", "b": "not_detected"},
            (0, 1),
        ),
        (
            "majority",
            {"a": "detected", "b": "detected"},
            (1, 1),
        ),
        (
            "majority",
            {"a": "detected", "b": "not_detected"},
            (0, 1),
        ),
        (
            "unanimous_detects",
            {"a": "not_detected", "b": "detected"},
            (0, 0),
        ),
        (
            "unanimous_detects",
            {"a": "detected", "b": "detected"},
            (0, 1),
        ),
    ),
)
def test_detection_bounds_are_sharp_under_one_missing_model(
    rule: str,
    decisions: dict[str, str],
    expected: tuple[int, int],
) -> None:
    result = detection_bounds(
        decisions=decisions,
        models=("a", "b", "c"),
        positive_decision="detected",
        negative_decision="not_detected",
        rule=rule,
    )

    assert (result["lower"], result["upper"]) == expected
    assert result["identified"] is (expected[0] == expected[1])
    assert result["missing_models"] == ["c"]


def test_detection_bounds_treat_abstention_as_unknown() -> None:
    result = detection_bounds(
        decisions={"a": "not_detected", "b": "abstain", "c": "not_detected"},
        models=("a", "b", "c"),
        positive_decision="detected",
        negative_decision="not_detected",
        rule="any_detect",
    )

    assert result == {
        "lower": 0,
        "upper": 1,
        "identified": False,
        "missing_models": [],
        "abstaining_models": ["b"],
    }


def test_paired_effect_bounds_use_opposite_endpoint_extremes() -> None:
    assert paired_effect_bounds((0, 1), (1, 1)) == (-1, 0)
    assert paired_effect_bounds((1, 1), (0, 1)) == (0, 1)
