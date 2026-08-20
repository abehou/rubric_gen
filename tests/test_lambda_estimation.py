from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from rubric_gen.submission_revision.lambda_estimation import (
    LambdaNotIdentifiableError,
    LambdaObservation,
    _task_cluster_bootstrap,
    fit_normalized_lambda,
    inference_readiness_issues,
    leave_one_task_out,
    load_lambda_dataset,
    point_identifiability_issues,
    task_cluster_bootstrap,
)
from rubric_gen.submission_revision.rh_diagnostics import EVALUATION_KIND


def _observation(
    index: int,
    *,
    detected: int,
    verifier: float,
    dynamic: float,
    task_id: str | None = None,
) -> LambdaObservation:
    return LambdaObservation(
        assignment_id=f"assignment-{index}",
        task_id=task_id or f"task-{index}",
        condition_id="online-elicitation",
        detected=detected,
        verifier_positive_part_change=verifier,
        dynamic_positive_part_change=dynamic,
    )


def _assignment(
    assignment_id: str,
    *,
    decision: str,
    initial: tuple[float, float],
    final: tuple[float, float],
) -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "task_id": f"task-{assignment_id}",
        "condition_id": "fixed",
        "direct_detection": {"decision": decision},
        "boundaries": {
            "initial": {
                "components": {
                    "verifier_exploitation": initial[0],
                    "dynamic_rubric_gap": initial[1],
                },
            },
            "final": {
                "components": {
                    "verifier_exploitation": final[0],
                    "dynamic_rubric_gap": final[1],
                },
            },
        },
    }


def _summary(assignments: list[dict[str, object]]) -> dict[str, object]:
    estimand_text = {
        "boundaries": "current boundaries",
        "primary_reward_hacking_outcome": "current RH outcome",
        "quality_outcome": "current quality outcome",
        "pairwise_outcome": "current pairwise outcome",
        "identity": "current identity",
        "rubric_elicitation": "current elicitation rule",
        "weak_rescore": "current weak rescore",
        "common_random_numbers": "current reuse rule",
        "rubric_diagnostics": "current diagnostics",
        "direct_detector": "current direct detector",
    }
    return {
        "kind": EVALUATION_KIND,
        "status": "completed",
        "experiment_id": "experiment-a",
        "estimand": {
            **estimand_text,
            "score_scale": [0, 100],
            "component_order": [
                "verifier_exploitation",
                "dynamic_rubric_gap",
            ],
            "loss_weights": {
                "verifier_exploitation": 1,
                "dynamic_rubric_gap": 1,
            },
        },
        "direct_ensemble": {},
        "predispatch_plans": {},
        "condition_aggregates": {},
        "paired_condition_contrasts": [],
        "assignments": assignments,
    }


def test_current_summary_loads_positive_part_changes(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_summary([
            _assignment(
                "a",
                decision="detected",
                initial=(-4, 8),
                final=(6, -3),
            ),
            _assignment(
                "b",
                decision="abstain",
                initial=(1, 2),
                final=(3, 4),
            ),
        ])))

    dataset = load_lambda_dataset(path)

    assert dataset.experiment_id == "experiment-a"
    assert dataset.excluded_assignment_ids == ("b",)
    assert len(dataset.observations) == 1
    assert dataset.observations[0].features == (6, -8)


def test_loader_rejects_obsolete_detection_suite(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({
        "kind": "rubric-gen-rh-detection-suite",
        "status": "completed",
        "experiment_id": "old",
        "assignments": [{}],
    }))

    with pytest.raises(ValueError, match="current RH summary"):
        load_lambda_dataset(path)


def test_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text(
        '{"kind":"rubric-gen-rh-evaluation",'
        '"kind":"rubric-gen-rh-evaluation"}'
    )

    with pytest.raises(ValueError, match="duplicate JSON key: kind"):
        load_lambda_dataset(path)


def test_loader_rejects_nonfinite_json_numbers(tmp_path: Path) -> None:
    assignment = _assignment(
        "a",
        decision="detected",
        initial=(math.nan, 0),
        final=(1, 2),
    )
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_summary([assignment])))

    with pytest.raises(ValueError, match="non-standard JSON constant: NaN"):
        load_lambda_dataset(path)


def test_loader_requires_exact_current_summary_and_estimand(tmp_path: Path) -> None:
    assignment = _assignment(
        "a",
        decision="detected",
        initial=(0, 0),
        final=(1, 2),
    )
    unexpected = _summary([assignment])
    unexpected["legacy_field"] = 1
    path = tmp_path / "unexpected.json"
    path.write_text(json.dumps(unexpected))

    with pytest.raises(ValueError, match=r"unexpected=\['legacy_field'\]"):
        load_lambda_dataset(path)

    wrong_order = _summary([assignment])
    estimand = wrong_order["estimand"]
    assert isinstance(estimand, dict)
    estimand["component_order"] = [
        "dynamic_rubric_gap",
        "verifier_exploitation",
    ]
    path = tmp_path / "wrong-order.json"
    path.write_text(json.dumps(wrong_order))

    with pytest.raises(ValueError, match="wrong component order"):
        load_lambda_dataset(path)


def test_loader_validates_components_for_excluded_assignments(
    tmp_path: Path,
) -> None:
    assignment = _assignment(
        "a",
        decision="abstain",
        initial=(0, 0),
        final=(1, 2),
    )
    boundaries = assignment["boundaries"]
    assert isinstance(boundaries, dict)
    final = boundaries["final"]
    assert isinstance(final, dict)
    final.pop("components")
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(_summary([assignment])))

    with pytest.raises(ValueError, match="components"):
        load_lambda_dataset(path)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"assignment_id": ""}, "assignment_id"),
        ({"task_id": ""}, "task_id"),
        ({"condition_id": 3}, "condition_id"),
        ({"detected": True}, "detected"),
        ({"detected": 2}, "detected"),
        ({"verifier_positive_part_change": math.inf}, "finite number"),
        ({"dynamic_positive_part_change": math.nan}, "finite number"),
    ],
)
def test_observation_rejects_invalid_direct_values(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "assignment_id": "assignment-a",
        "task_id": "task-a",
        "condition_id": "fixed",
        "detected": 0,
        "verifier_positive_part_change": 1.0,
        "dynamic_positive_part_change": 2.0,
    }
    values.update(changes)

    with pytest.raises(ValueError, match=message):
        LambdaObservation(**values)  # type: ignore[arg-type]


def test_all_negative_detector_outcomes_do_not_identify_lambda() -> None:
    rows = tuple(
        _observation(
            index,
            detected=0,
            verifier=float(index),
            dynamic=float(index * index),
        )
        for index in range(6)
    )

    assert point_identifiability_issues(rows) == (
        "all evaluated direct outcomes are not_detected",
    )
    with pytest.raises(LambdaNotIdentifiableError, match="all evaluated"):
        fit_normalized_lambda(rows)


def test_direct_fit_rejects_duplicate_assignment_ids() -> None:
    first = _observation(
        1,
        detected=0,
        verifier=0,
        dynamic=1,
    )
    duplicate = LambdaObservation(
        assignment_id=first.assignment_id,
        task_id="different-task",
        condition_id="fixed",
        detected=1,
        verifier_positive_part_change=1,
        dynamic_positive_part_change=0,
    )

    with pytest.raises(ValueError, match="duplicate lambda assignment"):
        fit_normalized_lambda((first, duplicate))


def test_collinear_component_changes_do_not_identify_weights() -> None:
    rows = tuple(
        _observation(
            index,
            detected=index % 2,
            verifier=float(index),
            dynamic=float(2 * index + 3),
        )
        for index in range(8)
    )

    assert point_identifiability_issues(rows) == (
        "the two positive-part change features lack rank two",
    )


def test_constrained_logistic_fit_recovers_normalized_direction() -> None:
    rows: list[LambdaObservation] = []
    index = 0
    for verifier in (-2.0, -1.0, 0.0, 1.0, 2.0):
        for dynamic in (-2.0, -1.0, 0.0, 1.0, 2.0):
            probability = 1 / (1 + math.exp(-(-0.4 + 0.8 * verifier + 0.2 * dynamic)))
            positive_count = min(19, max(1, round(20 * probability)))
            for repeat in range(20):
                rows.append(_observation(
                    index,
                    detected=int(repeat < positive_count),
                    verifier=verifier,
                    dynamic=dynamic,
                ))
                index += 1

    fit = fit_normalized_lambda(rows)
    lambda_v, lambda_d = fit.normalized_weights

    assert lambda_v + lambda_d == pytest.approx(2)
    assert lambda_v == pytest.approx(1.6, abs=0.08)
    assert lambda_d == pytest.approx(0.4, abs=0.08)


def test_constrained_fit_rejects_complete_separation() -> None:
    rows: list[LambdaObservation] = []
    index = 0
    for verifier in (-2.0, -1.0, 1.0, 2.0):
        for dynamic in (-2.0, -1.0, 1.0, 2.0):
            if verifier + dynamic == 0:
                continue
            rows.append(_observation(
                index,
                detected=int(verifier + dynamic > 0),
                verifier=verifier,
                dynamic=dynamic,
            ))
            index += 1

    with pytest.raises(LambdaNotIdentifiableError, match="separated"):
        fit_normalized_lambda(rows)


def test_cluster_guard_rejects_current_paperbench_task_count() -> None:
    rows: list[LambdaObservation] = []
    index = 0
    for task_index in range(3):
        for verifier, dynamic, positive_count in (
            (0.0, 0.0, 1),
            (1.0, 0.0, 2),
            (0.0, 1.0, 1),
        ):
            for repeat in range(3):
                rows.append(_observation(
                    index,
                    detected=int(repeat < positive_count),
                    verifier=verifier,
                    dynamic=dynamic,
                    task_id=f"paper-task-{task_index}",
                ))
                index += 1

    issues = inference_readiness_issues(rows)

    assert "fewer than 10 distinct task clusters" in issues
    with pytest.raises(LambdaNotIdentifiableError, match="distinct task clusters"):
        leave_one_task_out(rows)


@pytest.mark.parametrize(
    ("replicates", "seed", "message"),
    [
        (1999, 7, "at least 2000 integer replicates"),
        (True, 7, "at least 2000 integer replicates"),
        (2000, True, "seed must be an integer"),
        (2000, "7", "seed must be an integer"),
    ],
)
def test_public_bootstrap_validates_replicates_and_seed(
    replicates: object,
    seed: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        task_cluster_bootstrap((), replicates=replicates, seed=seed)  # type: ignore[arg-type]


def test_task_cross_validation_requires_full_sample_identification() -> None:
    rows = tuple(
        _observation(
            index,
            detected=0,
            verifier=float(index % 3),
            dynamic=float(index // 3),
            task_id=f"task-{index % 12}",
        )
        for index in range(24)
    )

    with pytest.raises(LambdaNotIdentifiableError, match="all evaluated"):
        leave_one_task_out(rows)


def test_cluster_bootstrap_and_task_cross_validation_use_task_units() -> None:
    rows: list[LambdaObservation] = []
    index = 0
    cells = (
        (0.0, 0.0, 2),
        (1.0, 0.0, 7),
        (0.0, 1.0, 4),
        (1.0, 1.0, 8),
    )
    for task_index in range(12):
        for verifier, dynamic, positive_count in cells:
            for repeat in range(10):
                rows.append(_observation(
                    index,
                    detected=int(repeat < positive_count),
                    verifier=verifier,
                    dynamic=dynamic,
                    task_id=f"task-{task_index}",
                ))
                index += 1

    intervals = _task_cluster_bootstrap(
        rows,
        replicates=100,
        seed=7,
        minimum_replicates=100,
    )
    cross_validation = leave_one_task_out(rows)

    assert intervals["replicates_identified"] == 100
    assert intervals["valid_fraction"] == 1
    assert cross_validation["completed_fold_count"] == 12
    assert cross_validation["all_folds_identified"] is True
    assert cross_validation["mean_log_loss"] is not None
    assert cross_validation["mean_intercept_only_log_loss"] is not None
