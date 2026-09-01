"""Validated result types for revision evaluation analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisMethod:
    unit: str
    pairing: str
    replicate_summary: str
    estimate: str
    interval: str
    confidence: float
    bootstrap_samples: int
    bootstrap_seed: int
    missing_values: str

    def record(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "pairing": self.pairing,
            "replicate_summary": self.replicate_summary,
            "estimate": self.estimate,
            "interval": self.interval,
            "confidence": self.confidence,
            "bootstrap_samples": self.bootstrap_samples,
            "bootstrap_seed": self.bootstrap_seed,
            "missing_values": self.missing_values,
        }


@dataclass(frozen=True, slots=True)
class MetricEstimate:
    estimate: float | None
    interval_95: tuple[float, float] | None
    task_count: int
    pair_count: int
    missing_pair_count: int

    def __post_init__(self) -> None:
        _validate_nonnegative(
            self.task_count,
            self.pair_count,
            self.missing_pair_count,
        )
        if (
            self.interval_95 is not None
            and self.interval_95[0] > self.interval_95[1]
        ):
            raise RuntimeError("evaluation metric interval is reversed")

    def record(self) -> dict[str, object]:
        return {
            "estimate": self.estimate,
            "interval_95": (
                list(self.interval_95) if self.interval_95 is not None else None
            ),
            "task_count": self.task_count,
            "pair_count": self.pair_count,
            "missing_pair_count": self.missing_pair_count,
        }


@dataclass(frozen=True, slots=True)
class BoundEstimate:
    estimate_bounds: tuple[float, float] | None
    task_count: int
    pair_count: int
    missing_pair_count: int

    def __post_init__(self) -> None:
        _validate_nonnegative(
            self.task_count,
            self.pair_count,
            self.missing_pair_count,
        )
        if (
            self.estimate_bounds is not None
            and self.estimate_bounds[0] > self.estimate_bounds[1]
        ):
            raise RuntimeError("evaluation bound estimate is reversed")

    def record(self) -> dict[str, object]:
        return {
            "estimate_bounds": (
                list(self.estimate_bounds)
                if self.estimate_bounds is not None
                else None
            ),
            "identified": (
                self.estimate_bounds is not None
                and self.estimate_bounds[0] == self.estimate_bounds[1]
            ),
            "task_count": self.task_count,
            "pair_count": self.pair_count,
            "missing_pair_count": self.missing_pair_count,
        }


@dataclass(frozen=True, slots=True)
class DetectionEffectBounds:
    direct_detection: BoundEstimate
    post_update_detection: BoundEstimate

    def record(self) -> dict[str, object]:
        return {
            "direct_detection": self.direct_detection.record(),
            "post_update_detection": self.post_update_detection.record(),
        }


MetricResults = tuple[tuple[str, MetricEstimate], ...]


@dataclass(frozen=True, slots=True)
class PairedSummary:
    left_count: int
    right_count: int
    pair_count: int
    unmatched_count: int
    metrics: MetricResults

    def __post_init__(self) -> None:
        _validate_nonnegative(
            self.left_count,
            self.right_count,
            self.pair_count,
            self.unmatched_count,
        )
        _validate_metrics(self.metrics)

    def record(self) -> dict[str, object]:
        return {
            "left_count": self.left_count,
            "right_count": self.right_count,
            "pair_count": self.pair_count,
            "unmatched_count": self.unmatched_count,
            "metrics": _metric_records(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class InteractionSummary:
    cell_counts: tuple[int, int, int, int]
    pair_count: int
    unmatched_count: int
    metrics: MetricResults

    def __post_init__(self) -> None:
        _validate_nonnegative(
            *self.cell_counts,
            self.pair_count,
            self.unmatched_count,
        )
        _validate_metrics(self.metrics)

    def record(self) -> dict[str, object]:
        return {
            "cell_counts": list(self.cell_counts),
            "pair_count": self.pair_count,
            "unmatched_count": self.unmatched_count,
            "metrics": _metric_records(self.metrics),
        }


@dataclass(frozen=True, slots=True)
class ConditionEffect:
    solver: str
    left_condition: str
    right_condition: str
    summary: PairedSummary
    detection_effect_bounds: DetectionEffectBounds | None

    def __post_init__(self) -> None:
        _validate_labels(self.solver, self.left_condition, self.right_condition)
        if self.left_condition == self.right_condition:
            raise RuntimeError("evaluation condition contrast has identical cells")

    def record(self) -> dict[str, object]:
        result = {
            "solver": self.solver,
            "left_condition": self.left_condition,
            "right_condition": self.right_condition,
            "direction": "left-minus-right",
            **self.summary.record(),
        }
        if self.detection_effect_bounds is not None:
            result["detection_effect_bounds"] = (
                self.detection_effect_bounds.record()
            )
        return result


@dataclass(frozen=True, slots=True)
class SolverEffect:
    condition: str
    left_solver: str
    right_solver: str
    summary: PairedSummary
    detection_effect_bounds: DetectionEffectBounds | None

    def __post_init__(self) -> None:
        _validate_labels(self.condition, self.left_solver, self.right_solver)
        if self.left_solver == self.right_solver:
            raise RuntimeError("evaluation solver contrast has identical cells")

    def record(self) -> dict[str, object]:
        result = {
            "condition": self.condition,
            "left_solver": self.left_solver,
            "right_solver": self.right_solver,
            "direction": "left-minus-right",
            **self.summary.record(),
        }
        if self.detection_effect_bounds is not None:
            result["detection_effect_bounds"] = (
                self.detection_effect_bounds.record()
            )
        return result


@dataclass(frozen=True, slots=True)
class InteractionEffect:
    left_solver: str
    right_solver: str
    left_condition: str
    right_condition: str
    summary: InteractionSummary
    detection_effect_bounds: DetectionEffectBounds | None

    def __post_init__(self) -> None:
        _validate_labels(
            self.left_solver,
            self.right_solver,
            self.left_condition,
            self.right_condition,
        )
        if self.left_solver == self.right_solver:
            raise RuntimeError("evaluation interaction has identical solvers")
        if self.left_condition == self.right_condition:
            raise RuntimeError("evaluation interaction has identical conditions")

    def record(self) -> dict[str, object]:
        result = {
            "left_solver": self.left_solver,
            "right_solver": self.right_solver,
            "left_condition": self.left_condition,
            "right_condition": self.right_condition,
            "direction": (
                "left-minus-right solver difference at left condition "
                "minus right condition"
            ),
            **self.summary.record(),
        }
        if self.detection_effect_bounds is not None:
            result["detection_effect_bounds"] = (
                self.detection_effect_bounds.record()
            )
        return result


@dataclass(frozen=True, slots=True)
class EffectCollection:
    condition_effects: tuple[ConditionEffect, ...]
    solver_effects: tuple[SolverEffect, ...]
    interactions: tuple[InteractionEffect, ...]

    def record(self) -> dict[str, object]:
        return {
            "condition_effects": [
                effect.record() for effect in self.condition_effects
            ],
            "solver_effects": [effect.record() for effect in self.solver_effects],
            "interactions": [effect.record() for effect in self.interactions],
        }


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    method: AnalysisMethod
    panel: EffectCollection
    judge_effects: tuple[tuple[str, EffectCollection], ...]

    def __post_init__(self) -> None:
        models = [model for model, _effects in self.judge_effects]
        if len(models) != len(set(models)) or any(not model for model in models):
            raise RuntimeError("evaluation judge effect identities are invalid")

    def record(self) -> dict[str, object]:
        return {
            "method": self.method.record(),
            **self.panel.record(),
            "judge_effects": {
                model: effects.record()
                for model, effects in self.judge_effects
            },
        }


def _validate_nonnegative(*values: int) -> None:
    if any(type(value) is not int or value < 0 for value in values):
        raise RuntimeError("evaluation result count is invalid")


def _validate_metrics(metrics: MetricResults) -> None:
    names = [name for name, _estimate in metrics]
    if len(names) != len(set(names)) or any(not name for name in names):
        raise RuntimeError("evaluation result metrics are invalid")


def _validate_labels(*values: str) -> None:
    if any(type(value) is not str or not value for value in values):
        raise RuntimeError("evaluation result identity is invalid")


def _metric_records(metrics: MetricResults) -> dict[str, object]:
    return {name: estimate.record() for name, estimate in metrics}
