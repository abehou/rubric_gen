"""Compute paired task-level effects for revision evaluations."""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations
from statistics import fmean, median

from rubric_gen.submission_revision.evaluation.analysis_observations import (
    AnalysisObservation,
    parse_analysis_observations,
)
from rubric_gen.submission_revision.evaluation.analysis_resampling import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    task_bootstrap_interval,
)
from rubric_gen.submission_revision.evaluation.analysis_results import (
    AnalysisMethod,
    AnalysisResult,
    BoundEstimate,
    ConditionEffect,
    DetectionEffectBounds,
    EffectCollection,
    InteractionEffect,
    InteractionSummary,
    MetricEstimate,
    PairedSummary,
    SolverEffect,
)
from rubric_gen.submission_revision.evaluation.panel_bounds import (
    paired_effect_bounds,
)


OUTCOME_NAMES = (
    "selected_rubric_gain",
    "holdout_rubric_gain",
    "rubric_free_absolute_score_gain",
    "original_rubric_weak_gain",
    "weak_to_strong_generalization_gap_change",
    "optimization_induced_risk",
    "reward_hacking_loss_change",
    "active_local_weak_gain",
    "active_local_strong_gain",
    "active_local_verifier_gap_change",
    "pairwise_preference_score",
)
COMPONENT_NAMES = (
    "verifier_exploitation",
    "original_rubric_gap",
)
DIAGNOSTIC_NAMES = (
    "active_to_original",
    "original_to_selected",
    "selected_rubric_minus_rubric_free_absolute_score",
)

CellKey = tuple[str, int]
MetricReader = Callable[[AnalysisObservation], float | None]


def parse_observations(
    assignments: list[dict[str, object]],
    models: tuple[str, ...],
    *,
    positive_decision: str,
    negative_decision: str,
) -> tuple[AnalysisObservation, ...]:
    return parse_analysis_observations(
        assignments,
        models,
        outcome_names=OUTCOME_NAMES,
        component_names=COMPONENT_NAMES,
        diagnostic_names=DIAGNOSTIC_NAMES,
        positive_decision=positive_decision,
        negative_decision=negative_decision,
    )


def describe(assignments: tuple[AnalysisObservation, ...]) -> dict[str, object]:
    """Return assignment-level summaries without inferential intervals."""

    if not assignments:
        raise RuntimeError("evaluation report has no assignments")
    conditions = _groups(assignments, "condition_id")
    solvers = _groups(assignments, "solver_id")
    policies = _groups(assignments, "rubric_policy")
    return {
        "conditions": _describe_groups({"all": assignments, **conditions}),
        "solvers": _describe_groups(solvers),
        "solver_conditions": {
            solver: _describe_groups({
                "all": members,
                **_groups(members, "condition_id"),
            })
            for solver, members in solvers.items()
        },
        "rubric_policies": _describe_groups(policies),
    }


def analyze(
    assignments: tuple[AnalysisObservation, ...],
    models: tuple[str, ...],
) -> AnalysisResult:
    """Return paired effects with tasks as the independent units."""

    if not assignments:
        raise RuntimeError("evaluation analysis has no assignments")
    if len(models) != len(set(models)) or any(not model for model in models):
        raise RuntimeError("evaluation analysis models are invalid")
    index = _cell_index(assignments)
    panel = _effect_sets(
        index,
        _panel_readers(),
        include_detection_bounds=True,
    )
    judge_effects = tuple(
        (
            model,
            _effect_sets(
                index,
                _judge_readers(model),
                include_detection_bounds=False,
            ),
        )
        for model in models
    )
    return AnalysisResult(
        method=AnalysisMethod(
            unit="task",
            pairing="task and replicate",
            replicate_summary="mean within task",
            estimate="mean across tasks",
            interval="percentile task bootstrap",
            confidence=0.95,
            bootstrap_samples=BOOTSTRAP_SAMPLES,
            bootstrap_seed=BOOTSTRAP_SEED,
            missing_values="excluded per metric and counted",
        ),
        panel=panel,
        judge_effects=judge_effects,
    )


def _groups(
    assignments: tuple[AnalysisObservation, ...],
    field: str,
) -> dict[str, tuple[AnalysisObservation, ...]]:
    groups: dict[str, list[AnalysisObservation]] = {}
    for assignment in assignments:
        value = getattr(assignment, field, None)
        if type(value) is not str or not value:
            raise RuntimeError(f"evaluation assignment has no {field}")
        groups.setdefault(value, []).append(assignment)
    return {
        name: tuple(members)
        for name, members in sorted(groups.items())
    }


def _describe_groups(
    groups: dict[str, tuple[AnalysisObservation, ...]],
) -> dict[str, object]:
    return {
        name: _describe_members(members)
        for name, members in groups.items()
    }


def _describe_members(
    members: tuple[AnalysisObservation, ...],
) -> dict[str, object]:
    return {
        "assignment_count": len(members),
        "outcomes": {
            name: _statistics([
                assignment.metric("outcomes", name)
                for assignment in members
            ])
            for name in OUTCOME_NAMES
        },
        "component_changes": {
            name: _statistics([
                assignment.metric("component_changes", name)
                for assignment in members
            ])
            for name in COMPONENT_NAMES
        },
        "rubric_diagnostic_changes": {
            name: _statistics([
                assignment.metric("rubric_diagnostic_changes", name)
                for assignment in members
            ])
            for name in DIAGNOSTIC_NAMES
        },
        "direct_detection": _describe_detection(members, "direct_detection"),
        "post_update_detection": _describe_detection(
            members,
            "post_update_detection",
        ),
    }


def _describe_detection(
    members: tuple[AnalysisObservation, ...],
    field: str,
) -> dict[str, object]:
    decisions = [assignment.detection(field).decision for assignment in members]
    detected = sum(value == "detected" for value in decisions)
    not_detected = sum(value == "not_detected" for value in decisions)
    abstained = sum(value == "abstain" for value in decisions)
    incomplete = sum(value == "incomplete" for value in decisions)
    evaluated = detected + not_detected
    bounds = [assignment.detection(field).bounds for assignment in members]
    return {
        "detected": detected,
        "not_detected": not_detected,
        "abstained": abstained,
        "incomplete": incomplete,
        "evaluated": evaluated,
        "rate": detected / evaluated if evaluated else None,
        "rate_bounds": [
            sum(lower for lower, _upper in bounds) / len(bounds),
            sum(upper for _lower, upper in bounds) / len(bounds),
        ],
    }


def _statistics(values: list[float]) -> dict[str, object]:
    positive = sum(value > 0 for value in values)
    return {
        "count": len(values),
        "mean": fmean(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
        "positive_count": positive,
        "positive_fraction": positive / len(values),
    }


def _cell_index(
    assignments: tuple[AnalysisObservation, ...],
) -> dict[tuple[str, int, str, str], AnalysisObservation]:
    result: dict[tuple[str, int, str, str], AnalysisObservation] = {}
    for assignment in assignments:
        key = assignment.cell_key
        if key in result:
            raise RuntimeError(f"duplicate evaluation analysis cell: {key}")
        result[key] = assignment
    return result


def _effect_sets(
    index: dict[tuple[str, int, str, str], AnalysisObservation],
    readers: dict[str, MetricReader],
    *,
    include_detection_bounds: bool,
) -> EffectCollection:
    solvers = sorted({key[2] for key in index})
    conditions = sorted({key[3] for key in index}, key=_condition_order)
    return EffectCollection(
        condition_effects=_condition_effects(
            index,
            solvers,
            conditions,
            readers,
            include_detection_bounds=include_detection_bounds,
        ),
        solver_effects=_solver_effects(
            index,
            solvers,
            conditions,
            readers,
            include_detection_bounds=include_detection_bounds,
        ),
        interactions=_interactions(
            index,
            solvers,
            conditions,
            readers,
            include_detection_bounds=include_detection_bounds,
        ),
    )


def _condition_effects(
    index: dict[tuple[str, int, str, str], AnalysisObservation],
    solvers: list[str],
    conditions: list[str],
    readers: dict[str, MetricReader],
    *,
    include_detection_bounds: bool,
) -> tuple[ConditionEffect, ...]:
    results: list[ConditionEffect] = []
    for solver in solvers:
        cells = {
            condition: _cells(index, solver=solver, condition=condition)
            for condition in conditions
        }
        for left, right in combinations(conditions, 2):
            results.append(ConditionEffect(
                solver=solver,
                left_condition=left,
                right_condition=right,
                summary=_paired_effect(cells[left], cells[right], readers),
                detection_effect_bounds=(
                    _paired_detection_effect_bounds(cells[left], cells[right])
                    if include_detection_bounds
                    else None
                ),
            ))
    return tuple(results)


def _solver_effects(
    index: dict[tuple[str, int, str, str], AnalysisObservation],
    solvers: list[str],
    conditions: list[str],
    readers: dict[str, MetricReader],
    *,
    include_detection_bounds: bool,
) -> tuple[SolverEffect, ...]:
    results: list[SolverEffect] = []
    for condition in conditions:
        cells = {
            solver: _cells(index, solver=solver, condition=condition)
            for solver in solvers
        }
        for left, right in combinations(solvers, 2):
            results.append(SolverEffect(
                condition=condition,
                left_solver=left,
                right_solver=right,
                summary=_paired_effect(cells[left], cells[right], readers),
                detection_effect_bounds=(
                    _paired_detection_effect_bounds(cells[left], cells[right])
                    if include_detection_bounds
                    else None
                ),
            ))
    return tuple(results)


def _interactions(
    index: dict[tuple[str, int, str, str], AnalysisObservation],
    solvers: list[str],
    conditions: list[str],
    readers: dict[str, MetricReader],
    *,
    include_detection_bounds: bool,
) -> tuple[InteractionEffect, ...]:
    results: list[InteractionEffect] = []
    for left_solver, right_solver in combinations(solvers, 2):
        for left_condition, right_condition in combinations(conditions, 2):
            cells = (
                _cells(
                    index,
                    solver=left_solver,
                    condition=left_condition,
                ),
                _cells(
                    index,
                    solver=right_solver,
                    condition=left_condition,
                ),
                _cells(
                    index,
                    solver=left_solver,
                    condition=right_condition,
                ),
                _cells(
                    index,
                    solver=right_solver,
                    condition=right_condition,
                ),
            )
            results.append(InteractionEffect(
                left_solver=left_solver,
                right_solver=right_solver,
                left_condition=left_condition,
                right_condition=right_condition,
                summary=_interaction_effect(cells, readers),
                detection_effect_bounds=(
                    _interaction_detection_effect_bounds(cells)
                    if include_detection_bounds
                    else None
                ),
            ))
    return tuple(results)


def _cells(
    index: dict[tuple[str, int, str, str], AnalysisObservation],
    *,
    solver: str,
    condition: str,
) -> dict[CellKey, AnalysisObservation]:
    return {
        (task, replicate): assignment
        for (task, replicate, current_solver, current_condition), assignment
        in index.items()
        if current_solver == solver and current_condition == condition
    }


def _paired_effect(
    left: dict[CellKey, AnalysisObservation],
    right: dict[CellKey, AnalysisObservation],
    readers: dict[str, MetricReader],
) -> PairedSummary:
    common = sorted(set(left) & set(right))
    return PairedSummary(
        left_count=len(left),
        right_count=len(right),
        pair_count=len(common),
        unmatched_count=len(set(left) ^ set(right)),
        metrics=tuple(
            (name, _summarize_samples({
                key: left_value - right_value
                for key in common
                if (left_value := reader(left[key])) is not None
                and (right_value := reader(right[key])) is not None
            }, expected_pairs=len(common)))
            for name, reader in readers.items()
        ),
    )


def _paired_detection_effect_bounds(
    left: dict[CellKey, AnalysisObservation],
    right: dict[CellKey, AnalysisObservation],
) -> DetectionEffectBounds:
    common = sorted(set(left) & set(right))
    values = {
        field: _summarize_bound_samples(
            {
                key: paired_effect_bounds(
                    left[key].detection(field).bounds,
                    right[key].detection(field).bounds,
                )
                for key in common
            },
            expected_pairs=len(common),
        )
        for field in ("direct_detection", "post_update_detection")
    }
    return DetectionEffectBounds(
        direct_detection=values["direct_detection"],
        post_update_detection=values["post_update_detection"],
    )


def _interaction_effect(
    cells: tuple[
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
    ],
    readers: dict[str, MetricReader],
) -> InteractionSummary:
    keys = [set(values) for values in cells]
    common = sorted(set.intersection(*keys))
    union = set.union(*keys)
    return InteractionSummary(
        cell_counts=tuple(len(values) for values in cells),
        pair_count=len(common),
        unmatched_count=len(union - set(common)),
        metrics=tuple(
            (name, _summarize_samples(
                _interaction_samples(cells, common, reader),
                expected_pairs=len(common),
            ))
            for name, reader in readers.items()
        ),
    )


def _interaction_detection_effect_bounds(
    cells: tuple[
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
    ],
) -> DetectionEffectBounds:
    keys = [set(values) for values in cells]
    common = sorted(set.intersection(*keys))
    values = {
        field: _summarize_bound_samples(
            {
                key: _interaction_bounds(
                    tuple(cell[key].detection(field).bounds for cell in cells)
                )
                for key in common
            },
            expected_pairs=len(common),
        )
        for field in ("direct_detection", "post_update_detection")
    }
    return DetectionEffectBounds(
        direct_detection=values["direct_detection"],
        post_update_detection=values["post_update_detection"],
    )


def _interaction_bounds(
    values: tuple[
        tuple[int, int],
        tuple[int, int],
        tuple[int, int],
        tuple[int, int],
    ],
) -> tuple[int, int]:
    left_solver_left, right_solver_left, left_solver_right, right_solver_right = (
        values
    )
    return (
        left_solver_left[0]
        - right_solver_left[1]
        - left_solver_right[1]
        + right_solver_right[0],
        left_solver_left[1]
        - right_solver_left[0]
        - left_solver_right[0]
        + right_solver_right[1],
    )


def _interaction_samples(
    cells: tuple[
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
        dict[CellKey, AnalysisObservation],
    ],
    common: list[CellKey],
    reader: MetricReader,
) -> dict[CellKey, float]:
    samples: dict[CellKey, float] = {}
    for key in common:
        values = tuple(reader(cell[key]) for cell in cells)
        if any(value is None for value in values):
            continue
        left_solver_left, right_solver_left, left_solver_right, right_solver_right = (
            float(value) for value in values if value is not None
        )
        samples[key] = (
            left_solver_left
            - right_solver_left
            - left_solver_right
            + right_solver_right
        )
    return samples


def _summarize_samples(
    samples: dict[CellKey, float],
    *,
    expected_pairs: int,
) -> MetricEstimate:
    by_task: dict[str, list[float]] = {}
    for (task, _replicate), value in samples.items():
        by_task.setdefault(task, []).append(value)
    task_values = [fmean(values) for _task, values in sorted(by_task.items())]
    return MetricEstimate(
        estimate=fmean(task_values) if task_values else None,
        interval_95=task_bootstrap_interval(task_values),
        task_count=len(task_values),
        pair_count=len(samples),
        missing_pair_count=expected_pairs - len(samples),
    )


def _summarize_bound_samples(
    samples: dict[CellKey, tuple[int, int]],
    *,
    expected_pairs: int,
) -> BoundEstimate:
    by_task: dict[str, list[tuple[int, int]]] = {}
    for (task, _replicate), bounds in samples.items():
        by_task.setdefault(task, []).append(bounds)
    task_bounds = [
        (
            fmean(lower for lower, _upper in values),
            fmean(upper for _lower, upper in values),
        )
        for _task, values in sorted(by_task.items())
    ]
    estimate_bounds = (
        (
            fmean(lower for lower, _upper in task_bounds),
            fmean(upper for _lower, upper in task_bounds),
        )
        if task_bounds
        else None
    )
    return BoundEstimate(
        estimate_bounds=estimate_bounds,
        task_count=len(task_bounds),
        pair_count=len(samples),
        missing_pair_count=expected_pairs - len(samples),
    )


def _panel_readers() -> dict[str, MetricReader]:
    readers: dict[str, MetricReader] = {
        "direct_detection": lambda assignment: _panel_detection_value(
            assignment,
            "direct_detection",
        ),
        "post_update_detection": lambda assignment: _panel_detection_value(
            assignment,
            "post_update_detection",
        ),
    }
    readers.update({
        name: (
            lambda assignment, current=name: assignment.metric("outcomes", current)
        )
        for name in OUTCOME_NAMES
    })
    readers.update({
        f"{name}_change": (
            lambda assignment, current=name: assignment.metric(
                "component_changes", current
            )
        )
        for name in COMPONENT_NAMES
    })
    readers.update({
        f"{name}_change": (
            lambda assignment, current=name: assignment.metric(
                "rubric_diagnostic_changes", current
            )
        )
        for name in DIAGNOSTIC_NAMES
    })
    return readers


def _judge_readers(model: str) -> dict[str, MetricReader]:
    names = (
        "direct_detection",
        "post_update_detection",
        "original_rubric_gain",
        "selected_rubric_gain",
        "holdout_rubric_gain",
        "active_rubric_gain",
        "absolute_score_gain",
        "pairwise_preference_score",
    )
    return {
        name: (
            lambda assignment, current=name: assignment.judge_metric(
                model,
                current,
            )
        )
        for name in names
    }


def _panel_detection_value(
    assignment: AnalysisObservation,
    field: str,
) -> float | None:
    decision = assignment.detection(field).decision
    if decision == "detected":
        return 1.0
    if decision == "not_detected":
        return 0.0
    return None


def _condition_order(condition: str) -> tuple[int, str]:
    for rank, suffix in enumerate(("online-rubric", "offline-rubric", "static")):
        if condition == suffix or condition.endswith(f"-{suffix}"):
            return rank, condition
    return 3, condition
