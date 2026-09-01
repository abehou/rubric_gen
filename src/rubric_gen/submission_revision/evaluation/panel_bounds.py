"""Identify binary panel outcomes and bounds with missing decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


PANEL_RULES = frozenset({"majority", "any_detect", "unanimous_detects"})


def detection_bounds(
    *,
    decisions: Mapping[str, str],
    models: Sequence[str],
    positive_decision: str,
    negative_decision: str,
    rule: str,
) -> dict[str, object]:
    """Return sharp binary bounds under all missing panel decisions."""

    if rule not in PANEL_RULES:
        raise ValueError("panel rule is invalid")
    configured = tuple(models)
    if not configured or len(set(configured)) != len(configured):
        raise ValueError("panel models must be unique and nonempty")
    if not set(decisions) <= set(configured):
        raise ValueError("panel decisions contain an unconfigured model")
    observed_values = set(decisions.values())
    if not observed_values <= {
        positive_decision,
        negative_decision,
        "abstain",
    }:
        raise ValueError("panel decision is invalid")

    positive_count = sum(
        decisions.get(model) == positive_decision
        for model in configured
    )
    abstaining_models = tuple(
        model for model in configured if decisions.get(model) == "abstain"
    )
    missing_models = tuple(
        model for model in configured if model not in decisions
    )
    unknown_count = len(abstaining_models) + len(missing_models)
    lower = int(_apply_rule(positive_count, len(configured), rule))
    upper = int(
        _apply_rule(
            positive_count + unknown_count,
            len(configured),
            rule,
        )
    )
    return {
        "lower": lower,
        "upper": upper,
        "identified": lower == upper,
        "missing_models": list(missing_models),
        "abstaining_models": list(abstaining_models),
    }


def paired_effect_bounds(
    left: tuple[int, int],
    right: tuple[int, int],
) -> tuple[int, int]:
    """Return sharp bounds for one paired left-minus-right effect."""

    if any(value not in {0, 1} for value in (*left, *right)):
        raise ValueError("binary outcome bounds must contain only zero or one")
    if left[0] > left[1] or right[0] > right[1]:
        raise ValueError("binary outcome bounds are reversed")
    return left[0] - right[1], left[1] - right[0]


def _apply_rule(positive_count: int, panel_size: int, rule: str) -> bool:
    if rule == "majority":
        return positive_count > panel_size / 2
    if rule == "any_detect":
        return positive_count > 0
    return positive_count == panel_size
