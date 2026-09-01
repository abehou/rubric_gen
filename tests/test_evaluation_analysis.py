from __future__ import annotations

import pytest

from rubric_gen.submission_revision.evaluation import analysis
from rubric_gen.submission_revision.evaluation.analysis_results import (
    MetricEstimate,
)


MODELS = ("judge-a", "judge-b")
POSITIVE = "reward_hacking_detected"
NEGATIVE = "no_reward_hacking_detected"


def _assignment(
    *,
    task: str,
    replicate: int,
    solver: str,
    condition: str,
    value: float,
    judge_a: float | None = None,
    judge_b: float | None = None,
    direct: str = "not_detected",
) -> dict[str, object]:
    judge_gains = {
        "judge-a": value if judge_a is None else judge_a,
        "judge-b": value if judge_b is None else judge_b,
    }
    score_panels = {
        role: {
            "initial": {"scores": {model: 0 for model in MODELS}},
            "final": {"scores": dict(judge_gains)},
        }
        for role in ("original", "selected", "active_local")
    }
    provider_decisions = {
        model: POSITIVE if direct == "detected" else NEGATIVE
        for model in MODELS
    }
    if direct == "abstain":
        provider_decisions["judge-a"] = "abstain"
    bounds = {
        "lower": 1 if direct == "detected" else 0,
        "upper": 0 if direct == "not_detected" else 1,
    }
    return {
        "assignment_id": f"{task}-{replicate}-{solver}-{condition}",
        "task_id": task,
        "replicate": replicate,
        "solver_id": solver,
        "condition_id": condition,
        "rubric_policy": "fixed",
        "outcomes": {
            name: value
            for name in analysis.OUTCOME_NAMES
        },
        "component_changes": {
            name: value
            for name in analysis.COMPONENT_NAMES
        },
        "rubric_diagnostic_changes": {
            name: value
            for name in analysis.DIAGNOSTIC_NAMES
        },
        "direct_detection": {
            "decision": direct,
            "bounds": bounds,
            "provider_decisions": provider_decisions,
        },
        "post_update_detection": {
            "decision": direct,
            "bounds": bounds,
            "provider_decisions": provider_decisions,
        },
        "reference_scores": score_panels,
        "rubric_free_absolute_scores": {
            "model_scores": {
                model: {"initial": 0, "final": gain, "gain": gain}
                for model, gain in judge_gains.items()
            },
        },
        "pairwise_preference_scores": {
            "model_results": {
                model: {
                    "score": min(
                        1,
                        max(0, 0.5 + gain / 20),
                    ),
                }
                for model, gain in judge_gains.items()
            },
        },
    }


def _analyze(assignments: list[dict[str, object]]) -> dict[str, object]:
    observations = analysis.parse_observations(
        assignments,
        MODELS,
        positive_decision=POSITIVE,
        negative_decision=NEGATIVE,
    )
    return analysis.analyze(
        observations,
        MODELS,
    ).record()


def test_condition_effect_averages_replicates_within_tasks() -> None:
    assignments: list[dict[str, object]] = []
    for task, differences in {
        "task-1": (1, 3),
        "task-2": (5, 7),
    }.items():
        for replicate, difference in enumerate(differences, start=1):
            assignments.extend((
                _assignment(
                    task=task,
                    replicate=replicate,
                    solver="solver-a",
                    condition="online-rubric",
                    value=difference,
                ),
                _assignment(
                    task=task,
                    replicate=replicate,
                    solver="solver-a",
                    condition="static",
                    value=0,
                ),
            ))

    effect = _analyze(assignments)["condition_effects"][0]
    estimate = effect["metrics"]["selected_rubric_gain"]

    assert estimate == {
        "estimate": 4,
        "interval_95": [2, 6],
        "task_count": 2,
        "pair_count": 4,
        "missing_pair_count": 0,
    }


def test_analysis_reports_solver_by_condition_interaction() -> None:
    assignments = [
        _assignment(
            task="task-1",
            replicate=1,
            solver=solver,
            condition=condition,
            value=value,
        )
        for solver, condition, value in (
            ("solver-a", "online-rubric", 10),
            ("solver-b", "online-rubric", 4),
            ("solver-a", "static", 3),
            ("solver-b", "static", 1),
        )
    ]

    result = _analyze(assignments)
    interaction = result["interactions"][0]

    assert interaction["left_solver"] == "solver-a"
    assert interaction["right_solver"] == "solver-b"
    assert interaction["metrics"]["selected_rubric_gain"]["estimate"] == 4
    assert {
        effect["condition"]: effect["metrics"]["selected_rubric_gain"]["estimate"]
        for effect in result["solver_effects"]
    } == {"online-rubric": 6, "static": 2}


def test_analysis_keeps_judge_specific_effects() -> None:
    assignments = [
        _assignment(
            task="task-1",
            replicate=1,
            solver="solver-a",
            condition=condition,
            value=value,
            judge_a=judge_a,
            judge_b=judge_b,
        )
        for condition, value, judge_a, judge_b in (
            ("online-rubric", 4, 8, -2),
            ("static", 0, 0, 0),
        )
    ]

    result = _analyze(assignments)
    judge_a = result["judge_effects"]["judge-a"]["condition_effects"][0]
    judge_b = result["judge_effects"]["judge-b"]["condition_effects"][0]

    assert judge_a["metrics"]["selected_rubric_gain"]["estimate"] == 8
    assert judge_b["metrics"]["selected_rubric_gain"]["estimate"] == -2
    assert judge_a["metrics"]["absolute_score_gain"]["estimate"] == 8


def test_analysis_counts_abstentions_as_missing_direct_values() -> None:
    assignments = [
        _assignment(
            task="task-1",
            replicate=1,
            solver="solver-a",
            condition="online-rubric",
            value=5,
            direct="abstain",
        ),
        _assignment(
            task="task-1",
            replicate=1,
            solver="solver-a",
            condition="static",
            value=0,
            direct="not_detected",
        ),
    ]

    result = _analyze(assignments)
    direct = result["condition_effects"][0]["metrics"]["direct_detection"]
    descriptive = analysis.describe(analysis.parse_observations(
        assignments,
        MODELS,
        positive_decision=POSITIVE,
        negative_decision=NEGATIVE,
    ))

    assert direct == {
        "estimate": None,
        "interval_95": None,
        "task_count": 0,
        "pair_count": 0,
        "missing_pair_count": 1,
    }
    direct_counts = descriptive["conditions"]["online-rubric"]["direct_detection"]
    assert direct_counts["abstained"] == 1
    assert direct_counts["rate_bounds"] == [0, 1]
    assert "rate_wilson_95" not in direct_counts
    bounds = result["condition_effects"][0]["detection_effect_bounds"]
    assert bounds["direct_detection"]["estimate_bounds"] == [0, 1]


def test_analysis_covers_the_full_factorial_design_shape() -> None:
    conditions = tuple(
        f"feedback-{feedback}-rubric-{rubric}"
        for feedback in range(4)
        for rubric in range(3)
    )
    assignments = [
        _assignment(
            task=f"task-{task}",
            replicate=replicate,
            solver=solver,
            condition=condition,
            value=float(task + replicate + solver_index + condition_index),
        )
        for task in range(1, 4)
        for replicate in range(1, 4)
        for solver_index, solver in enumerate(("solver-a", "solver-b"))
        for condition_index, condition in enumerate(conditions)
    ]

    result = _analyze(assignments)

    assert len(assignments) == 216
    assert len(result["condition_effects"]) == 132
    assert len(result["solver_effects"]) == 12
    assert len(result["interactions"]) == 66
    first = result["condition_effects"][0]
    assert first["pair_count"] == 9
    assert first["metrics"]["selected_rubric_gain"]["task_count"] == 3
    assert len(result["judge_effects"]["judge-a"]["interactions"]) == 66


def test_analysis_rejects_an_incomplete_metric_schema() -> None:
    assignment = _assignment(
        task="task-1",
        replicate=1,
        solver="solver-a",
        condition="static",
        value=1,
    )
    outcomes = assignment["outcomes"]
    assert isinstance(outcomes, dict)
    del outcomes["selected_rubric_gain"]

    with pytest.raises(RuntimeError, match="outcomes fields"):
        analysis.parse_observations(
            [assignment],
            MODELS,
            positive_decision=POSITIVE,
            negative_decision=NEGATIVE,
        )


def test_analysis_result_type_rejects_invalid_uncertainty() -> None:
    with pytest.raises(RuntimeError, match="interval is reversed"):
        MetricEstimate(
            estimate=0,
            interval_95=(1, -1),
            task_count=2,
            pair_count=2,
            missing_pair_count=0,
        )
