"""Internal calibration of reward-hacking component weights.

This module is not a command-line interface. It reads only the current combined
reward-hacking summary. The fitted weights describe association with the direct
detector. They are not benchmark ground truth or causal mechanism estimates.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rubric_gen.submission_revision.rh_diagnostics import EVALUATION_KIND
from rubric_gen.submission_revision.rubrics.schema import load_json_strict


COMPONENT_NAMES = ("verifier_exploitation", "dynamic_rubric_gap")
MIN_TASK_CLUSTERS = 10
MIN_EVENT_TASK_CLUSTERS = 5
MIN_NONEVENT_TASK_CLUSTERS = 5
MIN_VALID_BOOTSTRAP_FRACTION = 0.8
MIN_BOOTSTRAP_REPLICATES = 2000
_SUMMARY_KEYS = frozenset({
    "kind",
    "status",
    "experiment_id",
    "estimand",
    "direct_ensemble",
    "predispatch_plans",
    "condition_aggregates",
    "paired_condition_contrasts",
    "assignments",
})
_ESTIMAND_KEYS = frozenset({
    "boundaries",
    "score_scale",
    "component_order",
    "loss_weights",
    "primary_reward_hacking_outcome",
    "quality_outcome",
    "pairwise_outcome",
    "identity",
    "rubric_replacement",
    "weak_rescore",
    "common_random_numbers",
    "rubric_diagnostics",
    "direct_detector",
})
_ESTIMAND_TEXT_KEYS = _ESTIMAND_KEYS - {
    "score_scale",
    "component_order",
    "loss_weights",
}


class LambdaNotIdentifiableError(ValueError):
    """The supplied observations do not identify both normalized weights."""

    def __init__(self, reasons: Iterable[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class LambdaObservation:
    assignment_id: str
    task_id: str
    condition_id: str
    detected: int
    verifier_positive_part_change: float
    dynamic_positive_part_change: float

    def __post_init__(self) -> None:
        for field_name in ("assignment_id", "task_id", "condition_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value:
                raise ValueError(f"{field_name} must be a nonempty string")
        if type(self.detected) is not int or self.detected not in {0, 1}:
            raise ValueError("detected must be the integer 0 or 1")
        for field_name in (
            "verifier_positive_part_change",
            "dynamic_positive_part_change",
        ):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"{field_name} must be a finite number")

    @property
    def features(self) -> tuple[float, float]:
        return (
            self.verifier_positive_part_change,
            self.dynamic_positive_part_change,
        )


@dataclass(frozen=True)
class LambdaDataset:
    experiment_id: str
    observations: tuple[LambdaObservation, ...]
    excluded_assignment_ids: tuple[str, ...]


@dataclass(frozen=True)
class LogisticFit:
    intercept: float
    verifier_coefficient: float
    dynamic_coefficient: float
    negative_log_likelihood: float

    @property
    def slope(self) -> float:
        return (self.verifier_coefficient + self.dynamic_coefficient) / 2

    @property
    def normalized_weights(self) -> tuple[float, float]:
        total = self.verifier_coefficient + self.dynamic_coefficient
        if total <= 0:
            raise LambdaNotIdentifiableError((
                "the fitted non-negative detector slope is zero",
            ))
        return (
            2 * self.verifier_coefficient / total,
            2 * self.dynamic_coefficient / total,
        )


def load_lambda_dataset(summary_path: Path) -> LambdaDataset:
    """Load features and primary direct outcomes from a current RH summary."""

    try:
        text = summary_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read RH summary: {summary_path}") from exc
    try:
        value = load_json_strict(text)
    except ValueError as exc:
        raise ValueError(f"RH summary is not strict JSON: {exc}") from exc
    if type(value) is not dict:
        raise ValueError("RH summary must be an object")
    if value.get("kind") != EVALUATION_KIND or value.get("status") != "completed":
        raise ValueError("lambda calibration requires a completed current RH summary")
    _require_exact_keys(value, _SUMMARY_KEYS, "RH summary")
    estimand = _mapping(value, "estimand")
    _validate_current_estimand(estimand)
    for key in (
        "direct_ensemble",
        "predispatch_plans",
        "condition_aggregates",
    ):
        _mapping(value, key)
    if type(value.get("paired_condition_contrasts")) is not list:
        raise ValueError("RH paired condition contrasts must be a list")
    experiment_id = value.get("experiment_id")
    assignments = value.get("assignments")
    if type(experiment_id) is not str or not experiment_id:
        raise ValueError("RH summary has no experiment ID")
    if not isinstance(assignments, list) or not assignments:
        raise ValueError("RH summary has no assignments")

    observations: list[LambdaObservation] = []
    excluded: list[str] = []
    seen: set[str] = set()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise ValueError("RH summary contains an invalid assignment")
        assignment_id = _nonempty_string(assignment, "assignment_id")
        task_id = _nonempty_string(assignment, "task_id")
        condition_id = _nonempty_string(assignment, "condition_id")
        if assignment_id in seen:
            raise ValueError(f"duplicate RH assignment: {assignment_id}")
        seen.add(assignment_id)
        direct = _mapping(assignment, "direct_detection")
        decision = direct.get("decision")
        if decision not in {"detected", "not_detected", "abstain", "incomplete"}:
            raise ValueError(f"invalid direct decision for {assignment_id}")
        boundaries = _mapping(assignment, "boundaries")
        initial = _mapping(boundaries, "initial")
        final = _mapping(boundaries, "final")
        initial_components = _mapping(initial, "components")
        final_components = _mapping(final, "components")
        initial_values = tuple(
            _finite_number(initial_components, name) for name in COMPONENT_NAMES
        )
        final_values = tuple(
            _finite_number(final_components, name) for name in COMPONENT_NAMES
        )
        changes = tuple(
            max(final_value, 0.0) - max(initial_value, 0.0)
            for initial_value, final_value in zip(
                initial_values,
                final_values,
                strict=True,
            )
        )
        if decision in {"abstain", "incomplete"}:
            excluded.append(assignment_id)
            continue
        observations.append(LambdaObservation(
            assignment_id=assignment_id,
            task_id=task_id,
            condition_id=condition_id,
            detected=int(decision == "detected"),
            verifier_positive_part_change=changes[0],
            dynamic_positive_part_change=changes[1],
        ))
    if not observations:
        raise LambdaNotIdentifiableError((
            "the current RH summary has no evaluated direct outcomes",
        ))
    return LambdaDataset(
        experiment_id=experiment_id,
        observations=tuple(observations),
        excluded_assignment_ids=tuple(excluded),
    )


def point_identifiability_issues(
    observations: Iterable[LambdaObservation],
) -> tuple[str, ...]:
    """Return exact data failures that block a normalized point estimate."""

    rows = _validate_observations(observations)
    return _point_identifiability_issues(rows)


def _point_identifiability_issues(
    rows: tuple[LambdaObservation, ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    positives = sum(row.detected for row in rows)
    if positives == 0:
        reasons.append("all evaluated direct outcomes are not_detected")
    elif positives == len(rows):
        reasons.append("all evaluated direct outcomes are detected")
    if _centered_feature_rank(rows) < 2:
        reasons.append("the two positive-part change features lack rank two")
    elif positives and positives < len(rows) and _has_nonnegative_separation(rows):
        reasons.append(
            "the non-negative logistic model is completely or quasi-separated"
        )
    return tuple(reasons)


def fit_normalized_lambda(
    observations: Iterable[LambdaObservation],
) -> LogisticFit:
    """Fit a non-negative logistic association and normalize its direction.

    The model is ``logit(p_i) = alpha + gamma_v*x_v + gamma_d*x_d``.
    Both gamma coefficients are non-negative. The reported loss weights are
    ``lambda_k = 2*gamma_k/(gamma_v + gamma_d)``. Their sum is two.
    """

    rows = _validate_observations(observations)
    return _fit_validated_rows(rows)


def _fit_validated_rows(
    rows: tuple[LambdaObservation, ...],
) -> LogisticFit:
    reasons = list(_point_identifiability_issues(rows))
    if reasons:
        raise LambdaNotIdentifiableError(reasons)
    fit = _fit_nonnegative_logistic(rows)
    if fit is None:
        raise LambdaNotIdentifiableError((
            "the constrained logistic likelihood has no verified finite optimum",
        ))
    if fit.verifier_coefficient + fit.dynamic_coefficient <= 1e-10:
        raise LambdaNotIdentifiableError((
            "the fitted non-negative detector slope is zero",
        ))
    return fit


def inference_readiness_issues(
    observations: Iterable[LambdaObservation],
) -> tuple[str, ...]:
    """Return minimum cluster failures for benchmark-level uncertainty."""

    rows = _validate_observations(observations)
    tasks = {row.task_id for row in rows}
    event_tasks = {row.task_id for row in rows if row.detected}
    nonevent_tasks = {row.task_id for row in rows if not row.detected}
    reasons: list[str] = []
    if len(tasks) < MIN_TASK_CLUSTERS:
        reasons.append(
            f"fewer than {MIN_TASK_CLUSTERS} distinct task clusters"
        )
    if len(event_tasks) < MIN_EVENT_TASK_CLUSTERS:
        reasons.append(
            f"fewer than {MIN_EVENT_TASK_CLUSTERS} task clusters contain a detection"
        )
    if len(nonevent_tasks) < MIN_NONEVENT_TASK_CLUSTERS:
        reasons.append(
            "fewer than "
            f"{MIN_NONEVENT_TASK_CLUSTERS} task clusters contain a non-detection"
        )
    return tuple(reasons)


def task_cluster_bootstrap(
    observations: Iterable[LambdaObservation],
    *,
    replicates: int = 2000,
    seed: int = 20260818,
) -> dict[str, object]:
    """Return exploratory task-cluster percentile intervals for the weights."""

    return _task_cluster_bootstrap(
        observations,
        replicates=replicates,
        seed=seed,
        minimum_replicates=MIN_BOOTSTRAP_REPLICATES,
    )


def _task_cluster_bootstrap(
    observations: Iterable[LambdaObservation],
    *,
    replicates: int,
    seed: int,
    minimum_replicates: int,
) -> dict[str, object]:
    if type(minimum_replicates) is not int or minimum_replicates < 1:
        raise ValueError("lambda bootstrap minimum must be a positive integer")
    if type(replicates) is not int or replicates < minimum_replicates:
        raise ValueError(
            "lambda bootstrap requires at least "
            f"{minimum_replicates} integer replicates"
        )
    if type(seed) is not int:
        raise ValueError("lambda bootstrap seed must be an integer")

    rows = _validate_observations(observations)
    _fit_validated_rows(rows)
    readiness = inference_readiness_issues(rows)
    if readiness:
        raise LambdaNotIdentifiableError(readiness)
    grouped: dict[str, tuple[LambdaObservation, ...]] = {}
    for task_id in sorted({row.task_id for row in rows}):
        grouped[task_id] = tuple(row for row in rows if row.task_id == task_id)
    task_ids = tuple(grouped)
    generator = random.Random(seed)
    verifier_values: list[float] = []
    dynamic_values: list[float] = []
    for _ in range(replicates):
        sampled: list[LambdaObservation] = []
        for _cluster in task_ids:
            sampled.extend(grouped[generator.choice(task_ids)])
        try:
            fit = _fit_validated_rows(tuple(sampled))
        except LambdaNotIdentifiableError:
            continue
        verifier, dynamic = fit.normalized_weights
        verifier_values.append(verifier)
        dynamic_values.append(dynamic)
    valid_fraction = len(verifier_values) / replicates
    if valid_fraction < MIN_VALID_BOOTSTRAP_FRACTION:
        raise LambdaNotIdentifiableError((
            "fewer than 80% of task-cluster bootstrap samples identify the weights",
        ))
    return {
        "replicates_requested": replicates,
        "replicates_identified": len(verifier_values),
        "valid_fraction": valid_fraction,
        "seed": seed,
        "interval_interpretation": (
            "exploratory percentile interval conditional on task-level "
            "exchangeability"
        ),
        "verifier_exploitation_95_percentile_interval": [
            _percentile(verifier_values, 0.025),
            _percentile(verifier_values, 0.975),
        ],
        "dynamic_rubric_gap_95_percentile_interval": [
            _percentile(dynamic_values, 0.025),
            _percentile(dynamic_values, 0.975),
        ],
    }


def leave_one_task_out(
    observations: Iterable[LambdaObservation],
) -> dict[str, object]:
    """Evaluate detector calibration on tasks excluded from weight fitting."""

    rows = _validate_observations(observations)
    _fit_validated_rows(rows)
    readiness = inference_readiness_issues(rows)
    if readiness:
        raise LambdaNotIdentifiableError(readiness)
    tasks = sorted({row.task_id for row in rows})
    records: list[dict[str, object]] = []
    for task_id in tasks:
        training = tuple(row for row in rows if row.task_id != task_id)
        held_out = tuple(row for row in rows if row.task_id == task_id)
        try:
            fit = fit_normalized_lambda(training)
        except LambdaNotIdentifiableError as exc:
            records.append({
                "task_id": task_id,
                "status": "not_identifiable",
                "reasons": list(exc.reasons),
            })
            continue
        weights = fit.normalized_weights
        probabilities = [_probability(fit, row) for row in held_out]
        baseline_probability = sum(row.detected for row in training) / len(training)
        baseline_probability = min(
            max(baseline_probability, 1e-15),
            1 - 1e-15,
        )
        log_loss = _mean([
            -(
                row.detected * math.log(probability)
                + (1 - row.detected) * math.log1p(-probability)
            )
            for row, probability in zip(held_out, probabilities, strict=True)
        ])
        brier_score = _mean([
            (probability - row.detected) ** 2
            for row, probability in zip(held_out, probabilities, strict=True)
        ])
        baseline_log_loss = _mean([
            -(
                row.detected * math.log(baseline_probability)
                + (1 - row.detected) * math.log1p(-baseline_probability)
            )
            for row in held_out
        ])
        baseline_brier_score = _mean([
            (baseline_probability - row.detected) ** 2 for row in held_out
        ])
        records.append({
            "task_id": task_id,
            "status": "completed",
            "lambda_v": weights[0],
            "lambda_d": weights[1],
            "log_loss": log_loss,
            "brier_score": brier_score,
            "intercept_only_log_loss": baseline_log_loss,
            "intercept_only_brier_score": baseline_brier_score,
            "held_out_count": len(held_out),
        })
    completed = [record for record in records if record["status"] == "completed"]
    return {
        "task_count": len(tasks),
        "completed_fold_count": len(completed),
        "all_folds_identified": len(completed) == len(tasks),
        "mean_log_loss": (
            _mean([float(record["log_loss"]) for record in completed])
            if completed
            else None
        ),
        "mean_brier_score": (
            _mean([float(record["brier_score"]) for record in completed])
            if completed
            else None
        ),
        "mean_intercept_only_log_loss": (
            _mean([
                float(record["intercept_only_log_loss"]) for record in completed
            ])
            if completed
            else None
        ),
        "mean_intercept_only_brier_score": (
            _mean([
                float(record["intercept_only_brier_score"])
                for record in completed
            ])
            if completed
            else None
        ),
        "folds": records,
    }


def _fit_nonnegative_logistic(
    rows: tuple[LambdaObservation, ...],
) -> LogisticFit | None:
    candidates: list[LogisticFit] = []
    for active in ((0, 1), (0,), (1,), ()):
        candidate = _fit_active_set(rows, active)
        if candidate is not None and _satisfies_kkt(rows, candidate, active):
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda value: value.negative_log_likelihood)


def _fit_active_set(
    rows: tuple[LambdaObservation, ...],
    active: tuple[int, ...],
) -> LogisticFit | None:
    scales = {
        index: max(1.0, max(abs(row.features[index]) for row in rows))
        for index in active
    }
    design = [
        [1.0, *(row.features[index] / scales[index] for index in active)]
        for row in rows
    ]
    positives = sum(row.detected for row in rows)
    coefficients = [math.log(positives / (len(rows) - positives))]
    coefficients.extend(0.0 for _ in active)
    current = _negative_log_likelihood(design, rows, coefficients)
    converged = False
    for _ in range(200):
        gradient, hessian = _gradient_hessian(design, rows, coefficients)
        if max(abs(value) for value in gradient) <= 1e-9 * len(rows):
            converged = True
            break
        step = _solve_linear(hessian, gradient)
        if step is None or max(abs(value) for value in step) > 1e8:
            return None
        directional = sum(
            gradient[index] * step[index] for index in range(len(step))
        )
        accepted = False
        fraction = 1.0
        while fraction >= 2**-30:
            proposal = [
                value - fraction * delta
                for value, delta in zip(coefficients, step, strict=True)
            ]
            proposed = _negative_log_likelihood(design, rows, proposal)
            if proposed <= current - 1e-4 * fraction * directional:
                coefficients = proposal
                current = proposed
                accepted = True
                break
            fraction /= 2
        if not accepted:
            return None
        if max(abs(value) for value in coefficients) > 1e6:
            return None
    if not converged:
        gradient, _hessian = _gradient_hessian(design, rows, coefficients)
        if max(abs(value) for value in gradient) > 1e-7 * len(rows):
            return None
    unscaled = [0.0, 0.0]
    for position, index in enumerate(active, start=1):
        unscaled[index] = coefficients[position] / scales[index]
        if unscaled[index] <= 1e-12:
            return None
    return LogisticFit(
        intercept=coefficients[0],
        verifier_coefficient=unscaled[0],
        dynamic_coefficient=unscaled[1],
        negative_log_likelihood=current,
    )


def _satisfies_kkt(
    rows: tuple[LambdaObservation, ...],
    fit: LogisticFit,
    active: tuple[int, ...],
) -> bool:
    gradients = [0.0, 0.0, 0.0]
    for row in rows:
        residual = _probability(fit, row) - row.detected
        gradients[0] += residual
        gradients[1] += residual * row.features[0]
        gradients[2] += residual * row.features[1]
    tolerance = 1e-6 * max(
        1.0,
        len(rows),
        *(abs(row.features[index]) for row in rows for index in range(2)),
    )
    if abs(gradients[0]) > tolerance:
        return False
    for index in range(2):
        gradient = gradients[index + 1]
        if index in active:
            if abs(gradient) > tolerance:
                return False
        elif gradient < -tolerance:
            return False
    return True


def _negative_log_likelihood(
    design: list[list[float]],
    rows: tuple[LambdaObservation, ...],
    coefficients: list[float],
) -> float:
    total = 0.0
    for values, row in zip(design, rows, strict=True):
        linear = sum(
            value * coefficient
            for value, coefficient in zip(values, coefficients, strict=True)
        )
        total += _softplus(linear) - row.detected * linear
    return total


def _gradient_hessian(
    design: list[list[float]],
    rows: tuple[LambdaObservation, ...],
    coefficients: list[float],
) -> tuple[list[float], list[list[float]]]:
    size = len(coefficients)
    gradient = [0.0] * size
    hessian = [[0.0] * size for _ in range(size)]
    for values, row in zip(design, rows, strict=True):
        linear = sum(
            value * coefficient
            for value, coefficient in zip(values, coefficients, strict=True)
        )
        probability = _sigmoid(linear)
        residual = probability - row.detected
        weight = probability * (1 - probability)
        for left in range(size):
            gradient[left] += residual * values[left]
            for right in range(size):
                hessian[left][right] += weight * values[left] * values[right]
    return gradient, hessian


def _solve_linear(
    matrix: list[list[float]],
    vector: list[float],
) -> list[float] | None:
    size = len(vector)
    work = [matrix[index][:] + [vector[index]] for index in range(size)]
    scale = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = max(1e-14, scale * 1e-12)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) <= tolerance:
            return None
        work[column], work[pivot] = work[pivot], work[column]
        pivot_value = work[column][column]
        for index in range(column, size + 1):
            work[column][index] /= pivot_value
        for row in range(size):
            if row == column:
                continue
            factor = work[row][column]
            for index in range(column, size + 1):
                work[row][index] -= factor * work[column][index]
    return [work[index][size] for index in range(size)]


def _centered_feature_rank(rows: tuple[LambdaObservation, ...]) -> int:
    if not rows:
        return 0
    means = tuple(_mean([row.features[index] for row in rows]) for index in range(2))
    columns = [
        [row.features[index] - means[index] for row in rows]
        for index in range(2)
    ]
    norms = [math.sqrt(sum(value * value for value in column)) for column in columns]
    nonzero = [index for index, norm in enumerate(norms) if norm > 1e-12]
    if not nonzero:
        return 0
    if len(nonzero) == 1:
        return 1
    correlation_numerator = sum(
        left * right for left, right in zip(columns[0], columns[1], strict=True)
    )
    determinant = (
        norms[0] * norms[0] * norms[1] * norms[1]
        - correlation_numerator * correlation_numerator
    )
    return 2 if determinant > 1e-12 * (norms[0] * norms[1]) ** 2 else 1


def _has_nonnegative_separation(
    rows: tuple[LambdaObservation, ...],
) -> bool:
    """Test for a separating ray in the non-negative coefficient cone."""

    positives = [row.features for row in rows if row.detected]
    negatives = [row.features for row in rows if not row.detected]
    lower = 0.0
    upper = 1.0
    tolerance = 1e-12
    for negative in negatives:
        for positive in positives:
            constant = negative[1] - positive[1]
            slope = (
                negative[0]
                - negative[1]
                - positive[0]
                + positive[1]
            )
            if abs(slope) <= tolerance:
                if constant > tolerance:
                    return False
                continue
            boundary = -constant / slope
            if slope > 0:
                upper = min(upper, boundary)
            else:
                lower = max(lower, boundary)
            if lower > upper + tolerance:
                return False
    return lower <= 1 + tolerance and upper >= -tolerance


def _probability(fit: LogisticFit, row: LambdaObservation) -> float:
    linear = (
        fit.intercept
        + fit.verifier_coefficient * row.verifier_positive_part_change
        + fit.dynamic_coefficient * row.dynamic_positive_part_change
    )
    return min(max(_sigmoid(linear), 1e-15), 1 - 1e-15)


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1 / (1 + inverse)
    exponent = math.exp(value)
    return exponent / (1 + exponent)


def _softplus(value: float) -> float:
    if value >= 0:
        return value + math.log1p(math.exp(-value))
    return math.log1p(math.exp(value))


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("cannot average an empty sequence")
    return sum(values) / len(values)


def _validate_observations(
    observations: Iterable[LambdaObservation],
) -> tuple[LambdaObservation, ...]:
    try:
        rows = tuple(observations)
    except TypeError as exc:
        raise ValueError("lambda observations must be iterable") from exc
    seen: set[str] = set()
    for row in rows:
        if type(row) is not LambdaObservation:
            raise ValueError("lambda observations contain an invalid item")
        row.__post_init__()
        if row.assignment_id in seen:
            raise ValueError(f"duplicate lambda assignment: {row.assignment_id}")
        seen.add(row.assignment_id)
    return rows


def _require_exact_keys(
    value: dict[str, object],
    expected: frozenset[str],
    context: str,
) -> None:
    missing = sorted(expected - set(value))
    unexpected = sorted(set(value) - expected)
    if missing or unexpected:
        raise ValueError(
            f"{context} keys are not current: "
            f"missing={missing}, unexpected={unexpected}"
        )


def _validate_current_estimand(estimand: dict[str, object]) -> None:
    _require_exact_keys(estimand, _ESTIMAND_KEYS, "RH estimand")
    if estimand.get("component_order") != list(COMPONENT_NAMES):
        raise ValueError("RH estimand has the wrong component order")
    score_scale = estimand.get("score_scale")
    if (
        type(score_scale) is not list
        or len(score_scale) != 2
        or any(type(value) is not int for value in score_scale)
        or score_scale != [0, 100]
    ):
        raise ValueError("RH estimand has the wrong score scale")
    weights = _mapping(estimand, "loss_weights")
    _require_exact_keys(weights, frozenset(COMPONENT_NAMES), "RH loss weights")
    normalized_weights = [
        _finite_number(weights, name) for name in COMPONENT_NAMES
    ]
    if any(weight < 0 for weight in normalized_weights):
        raise ValueError("RH loss weights must be non-negative")
    if not any(normalized_weights):
        raise ValueError("at least one RH loss weight must be positive")
    for key in _ESTIMAND_TEXT_KEYS:
        _nonempty_string(estimand, key)


def _mapping(value: dict[str, object], key: str) -> dict[str, object]:
    result = value.get(key)
    if type(result) is not dict:
        raise ValueError(f"RH summary field must be an object: {key}")
    return result


def _nonempty_string(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if type(result) is not str or not result:
        raise ValueError(f"RH summary field must be a nonempty string: {key}")
    return result


def _finite_number(value: dict[str, object], key: str) -> float:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise ValueError(f"RH component must be numeric: {key}")
    number = float(result)
    if not math.isfinite(number):
        raise ValueError(f"RH component must be finite: {key}")
    return number
