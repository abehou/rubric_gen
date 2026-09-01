"""Validate evaluation report rows before statistical analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DetectionObservation:
    decision: str
    bounds: tuple[int, int]
    provider_decisions: tuple[tuple[str, str], ...]

    def provider_value(
        self,
        model: str,
        *,
        positive_decision: str,
        negative_decision: str,
    ) -> float | None:
        decisions = dict(self.provider_decisions)
        if model not in decisions or decisions[model] == "abstain":
            return None
        if decisions[model] == positive_decision:
            return 1.0
        if decisions[model] == negative_decision:
            return 0.0
        raise RuntimeError("evaluation judge detection decision is invalid")


@dataclass(frozen=True, slots=True)
class JudgeObservation:
    model: str
    direct_detection: float | None
    post_update_detection: float | None
    original_rubric_gain: float | None
    selected_rubric_gain: float | None
    active_rubric_gain: float | None
    absolute_score_gain: float | None
    pairwise_preference_score: float | None

    def metric(self, name: str) -> float | None:
        values = {
            "direct_detection": self.direct_detection,
            "post_update_detection": self.post_update_detection,
            "original_rubric_gain": self.original_rubric_gain,
            "selected_rubric_gain": self.selected_rubric_gain,
            "active_rubric_gain": self.active_rubric_gain,
            "absolute_score_gain": self.absolute_score_gain,
            "pairwise_preference_score": self.pairwise_preference_score,
        }
        try:
            return values[name]
        except KeyError as exc:
            raise RuntimeError(f"unknown judge metric: {name}") from exc


@dataclass(frozen=True, slots=True)
class AnalysisObservation:
    assignment_id: str
    task_id: str
    replicate: int
    solver_id: str
    condition_id: str
    rubric_policy: str
    outcomes: tuple[tuple[str, float], ...]
    component_changes: tuple[tuple[str, float], ...]
    rubric_diagnostic_changes: tuple[tuple[str, float], ...]
    direct_detection: DetectionObservation
    post_update_detection: DetectionObservation
    judges: tuple[JudgeObservation, ...]

    @property
    def cell_key(self) -> tuple[str, int, str, str]:
        return self.task_id, self.replicate, self.solver_id, self.condition_id

    def metric(self, category: str, name: str) -> float:
        categories = {
            "outcomes": self.outcomes,
            "component_changes": self.component_changes,
            "rubric_diagnostic_changes": self.rubric_diagnostic_changes,
        }
        try:
            values = categories[category]
        except KeyError as exc:
            raise RuntimeError(f"unknown evaluation metric category: {category}") from exc
        try:
            return dict(values)[name]
        except KeyError as exc:
            raise RuntimeError(f"evaluation {category} has no {name}") from exc

    def detection(self, field: str) -> DetectionObservation:
        if field == "direct_detection":
            return self.direct_detection
        if field == "post_update_detection":
            return self.post_update_detection
        raise RuntimeError(f"unknown evaluation detection field: {field}")

    def judge_metric(self, model: str, name: str) -> float | None:
        matches = [judge for judge in self.judges if judge.model == model]
        if len(matches) != 1:
            raise RuntimeError(f"evaluation has no unique judge observation: {model}")
        return matches[0].metric(name)


def parse_analysis_observations(
    assignments: list[dict[str, object]],
    models: tuple[str, ...],
    *,
    outcome_names: tuple[str, ...],
    component_names: tuple[str, ...],
    diagnostic_names: tuple[str, ...],
    positive_decision: str,
    negative_decision: str,
) -> tuple[AnalysisObservation, ...]:
    """Convert report dictionaries into validated immutable observations."""

    if not assignments:
        raise RuntimeError("evaluation analysis has no assignments")
    if len(models) != len(set(models)) or any(not model for model in models):
        raise RuntimeError("evaluation analysis models are invalid")
    observations = tuple(
        _parse_observation(
            assignment,
            models,
            outcome_names=outcome_names,
            component_names=component_names,
            diagnostic_names=diagnostic_names,
            positive_decision=positive_decision,
            negative_decision=negative_decision,
        )
        for assignment in assignments
    )
    keys = [observation.cell_key for observation in observations]
    if len(keys) != len(set(keys)):
        raise RuntimeError("evaluation analysis contains duplicate cells")
    assignment_ids = [observation.assignment_id for observation in observations]
    if len(assignment_ids) != len(set(assignment_ids)):
        raise RuntimeError("evaluation analysis contains duplicate assignment IDs")
    return observations


def _parse_observation(
    assignment: dict[str, object],
    models: tuple[str, ...],
    *,
    outcome_names: tuple[str, ...],
    component_names: tuple[str, ...],
    diagnostic_names: tuple[str, ...],
    positive_decision: str,
    negative_decision: str,
) -> AnalysisObservation:
    assignment_id = _required_text(assignment, "assignment_id")
    task_id = _required_text(assignment, "task_id")
    replicate = assignment.get("replicate")
    if type(replicate) is not int or replicate < 1:
        raise RuntimeError("evaluation assignment replicate is invalid")
    direct = _detection(assignment, "direct_detection")
    post_update = _detection(assignment, "post_update_detection")
    return AnalysisObservation(
        assignment_id=assignment_id,
        task_id=task_id,
        replicate=replicate,
        solver_id=_required_text(assignment, "solver_id"),
        condition_id=_required_text(assignment, "condition_id"),
        rubric_policy=_required_text(assignment, "rubric_policy"),
        outcomes=_metrics(assignment, "outcomes", outcome_names),
        component_changes=_metrics(
            assignment,
            "component_changes",
            component_names,
        ),
        rubric_diagnostic_changes=_metrics(
            assignment,
            "rubric_diagnostic_changes",
            diagnostic_names,
        ),
        direct_detection=direct,
        post_update_detection=post_update,
        judges=tuple(
            _judge_observation(
                assignment,
                model,
                direct,
                post_update,
                positive_decision=positive_decision,
                negative_decision=negative_decision,
            )
            for model in models
        ),
    )


def _judge_observation(
    assignment: dict[str, object],
    model: str,
    direct: DetectionObservation,
    post_update: DetectionObservation,
    *,
    positive_decision: str,
    negative_decision: str,
) -> JudgeObservation:
    return JudgeObservation(
        model=model,
        direct_detection=direct.provider_value(
            model,
            positive_decision=positive_decision,
            negative_decision=negative_decision,
        ),
        post_update_detection=post_update.provider_value(
            model,
            positive_decision=positive_decision,
            negative_decision=negative_decision,
        ),
        original_rubric_gain=_rubric_gain(assignment, model, "original"),
        selected_rubric_gain=_rubric_gain(assignment, model, "selected"),
        active_rubric_gain=_rubric_gain(assignment, model, "active_local"),
        absolute_score_gain=_absolute_gain(assignment, model),
        pairwise_preference_score=_pairwise_score(assignment, model),
    )


def _metrics(
    assignment: dict[str, object],
    category: str,
    names: tuple[str, ...],
) -> tuple[tuple[str, float], ...]:
    values = _mapping(assignment, category)
    if set(values) != set(names):
        raise RuntimeError(f"evaluation {category} fields are invalid")
    return tuple(
        (name, _finite(values[name], f"evaluation {category} {name}"))
        for name in names
    )


def _detection(
    assignment: dict[str, object],
    field: str,
) -> DetectionObservation:
    value = _mapping(assignment, field)
    decision = value.get("decision")
    if decision not in {"detected", "not_detected", "abstain", "incomplete"}:
        raise RuntimeError(f"evaluation {field} decision is invalid")
    bounds = _mapping(value, "bounds")
    lower = bounds.get("lower")
    upper = bounds.get("upper")
    if (
        type(lower) is not int
        or type(upper) is not int
        or lower not in {0, 1}
        or upper not in {0, 1}
        or lower > upper
    ):
        raise RuntimeError(f"evaluation {field} bounds are invalid")
    providers = _mapping(value, "provider_decisions")
    if any(type(model) is not str or type(result) is not str for model, result in providers.items()):
        raise RuntimeError(f"evaluation {field} provider decisions are invalid")
    return DetectionObservation(
        decision=str(decision),
        bounds=(lower, upper),
        provider_decisions=tuple(sorted(
            (str(model), str(result)) for model, result in providers.items()
        )),
    )


def _rubric_gain(
    assignment: dict[str, object],
    model: str,
    role: str,
) -> float | None:
    reference = _mapping(assignment, "reference_scores")
    role_scores = _mapping(reference, role)
    initial = _panel_score(role_scores, "initial", model)
    final = _panel_score(role_scores, "final", model)
    return None if initial is None or final is None else final - initial


def _panel_score(
    role_scores: dict[str, object],
    artifact: str,
    model: str,
) -> float | None:
    scores = _mapping(_mapping(role_scores, artifact), "scores")
    return (
        None
        if model not in scores
        else _finite(scores[model], f"evaluation {artifact} judge score")
    )


def _absolute_gain(
    assignment: dict[str, object],
    model: str,
) -> float | None:
    scores = _mapping(
        _mapping(assignment, "rubric_free_absolute_scores"),
        "model_scores",
    )
    if model not in scores:
        return None
    model_scores = scores[model]
    if not isinstance(model_scores, dict):
        raise RuntimeError("evaluation absolute judge scores are invalid")
    return _finite(model_scores.get("gain"), "evaluation absolute judge gain")


def _pairwise_score(
    assignment: dict[str, object],
    model: str,
) -> float | None:
    scores = _mapping(
        _mapping(assignment, "pairwise_preference_scores"),
        "model_results",
    )
    if model not in scores:
        return None
    model_score = scores[model]
    if not isinstance(model_score, dict):
        raise RuntimeError("evaluation pairwise judge score is invalid")
    return _finite(
        model_score.get("score"),
        "evaluation pairwise judge preference",
    )


def _required_text(value: dict[str, object], name: str) -> str:
    result = value.get(name)
    if type(result) is not str or not result:
        raise RuntimeError(f"evaluation assignment has no {name}")
    return result


def _mapping(value: dict[str, object], name: str) -> dict[str, object]:
    result = value.get(name)
    if not isinstance(result, dict):
        raise RuntimeError(f"evaluation {name} is invalid")
    return result


def _finite(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise RuntimeError(f"{label} is invalid")
    return float(value)
