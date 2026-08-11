"""Analyze assignment rubric scores against reward-hacking detections.

The completed semi- and full-feedback studies each contain 360 assignments.
Each assignment has 11 rubric scores and one final three-model RH audit. This
script joins those records and reports raw point-biserial correlations plus
task-, study-, prompt-, and rubric-policy-adjusted linear risk slopes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_rubric_metadata_rh import (  # noqa: E402
    MAJORITY_DETECTOR,
    STUDIES,
    _load_assignments,
    _load_detection_outcomes,
    _load_json,
)


DEFAULT_OUTPUT_DIR = ROOT / "analyses" / "luna-top30-rubric-score-rh"
ANY_DETECTOR = "complete-panel-any-detector"


@dataclass(frozen=True)
class ScoreRow:
    study: str
    experiment_id: str
    task_id: str
    replicate: int
    prompt: str
    rubric_policy: str
    condition_id: str
    assignment_id: str
    scores: tuple[float, ...]
    outcomes: dict[str, int | None]


@dataclass(frozen=True)
class Feature:
    name: str
    label: str
    value: Callable[[ScoreRow], float]


@dataclass(frozen=True)
class Scope:
    name: str
    label: str
    keep: Callable[[ScoreRow], bool]


FEATURES = (
    Feature("baseline_score", "Baseline score", lambda row: row.scores[0]),
    Feature("final_score", "Final score", lambda row: row.scores[-1]),
    Feature(
        "score_gain",
        "Final minus baseline score",
        lambda row: row.scores[-1] - row.scores[0],
    ),
    Feature(
        "mean_post_score",
        "Mean score after baseline",
        lambda row: float(np.mean(row.scores[1:])),
    ),
)


SCOPES = (
    Scope("pooled", "Pooled", lambda row: True),
    Scope("full", "Full feedback", lambda row: row.study == "full"),
    Scope("semi", "Semi feedback", lambda row: row.study == "semi"),
    Scope(
        "full-static",
        "Full, static",
        lambda row: row.study == "full" and row.rubric_policy == "static",
    ),
    Scope(
        "full-prospective",
        "Full, prospective",
        lambda row: row.study == "full" and row.rubric_policy == "prospective",
    ),
    Scope(
        "semi-static",
        "Semi, static",
        lambda row: row.study == "semi" and row.rubric_policy == "static",
    ),
    Scope(
        "semi-prospective",
        "Semi, prospective",
        lambda row: row.study == "semi" and row.rubric_policy == "prospective",
    ),
)


SCORE_BANDS = (
    ("0-49", 0.0, 50.0),
    ("50-69", 50.0, 70.0),
    ("70-79", 70.0, 80.0),
    ("80-89", 80.0, 90.0),
    ("90-99", 90.0, 100.0),
    ("100", 100.0, 101.0),
)


def _stable_seed(*parts: object) -> int:
    text = "|".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(text).digest()[:8], "big")


def _load_rows() -> tuple[list[ScoreRow], list[str]]:
    rows: list[ScoreRow] = []
    detector_models: list[str] | None = None
    for spec in STUDIES:
        assignments = _load_assignments(spec)
        panels, models, _decision_counts = _load_detection_outcomes(spec)
        if detector_models is None:
            detector_models = models
        elif detector_models != models:
            raise ValueError("detector model order differs between studies")
        for key, assignment in sorted(assignments.items()):
            state = _load_json(assignment.directory / "state.json")
            scores_value = state.get("scores")
            if (
                not isinstance(scores_value, list)
                or len(scores_value) != 11
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or not 0 <= float(value) <= 100
                    for value in scores_value
                )
            ):
                raise ValueError(f"invalid score trajectory: {assignment.assignment_id}")
            scores = tuple(float(value) for value in scores_value)
            panel = panels[key]
            strict_votes = [panel[model] for model in models]
            strict_any = (
                int(any(vote == 1 for vote in strict_votes))
                if all(vote is not None for vote in strict_votes)
                else None
            )
            outcomes = {
                MAJORITY_DETECTOR: panel[MAJORITY_DETECTOR],
                ANY_DETECTOR: strict_any,
                **{model: panel[model] for model in models},
            }
            rows.append(
                ScoreRow(
                    study=assignment.study,
                    experiment_id=assignment.experiment_id,
                    task_id=assignment.task_id,
                    replicate=assignment.replicate,
                    prompt=assignment.prompt,
                    rubric_policy=assignment.rubric_policy,
                    condition_id=assignment.condition_id,
                    assignment_id=assignment.assignment_id,
                    scores=scores,
                    outcomes=outcomes,
                )
            )
    if len(rows) != 720 or detector_models is None:
        raise ValueError(f"expected 720 assignments; found {len(rows)}")
    return rows, detector_models


def _stratum_key(row: ScoreRow) -> tuple[str, str, str, str]:
    return row.task_id, row.study, row.prompt, row.rubric_policy


def _residualize(rows: Sequence[ScoreRow], values: np.ndarray) -> np.ndarray:
    groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[_stratum_key(row)].append(index)
    residuals = values.astype(float).copy()
    for indices in groups.values():
        residuals[indices] -= float(np.mean(residuals[indices]))
    return residuals


def _correlation(x_values: np.ndarray, y_values: np.ndarray) -> float:
    x_centered = x_values - float(np.mean(x_values))
    y_centered = y_values - float(np.mean(y_values))
    denominator = float(np.sqrt((x_centered @ x_centered) * (y_centered @ y_centered)))
    return float((x_centered @ y_centered) / denominator) if denominator > 0 else math.nan


def _quantile_interval(values: np.ndarray) -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return math.nan, math.nan
    return float(np.quantile(finite, 0.025)), float(np.quantile(finite, 0.975))


def _raw_task_bootstrap(
    rows: Sequence[ScoreRow],
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    draws: int,
    seed: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    by_task: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_task[row.task_id].append(index)
    tasks = sorted(by_task)
    task_stats = np.asarray(
        [
            (
                float(len(indices)),
                float(np.sum(x_values[indices])),
                float(np.sum(y_values[indices])),
                float(x_values[indices] @ x_values[indices]),
                float(y_values[indices] @ y_values[indices]),
                float(x_values[indices] @ y_values[indices]),
            )
            for indices in (by_task[task] for task in tasks)
        ],
        dtype=float,
    )
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(tasks), size=(draws, len(tasks)))
    sampled = task_stats[selected].sum(axis=1)
    n, sum_x, sum_y, sum_x2, sum_y2, sum_xy = sampled.T
    covariance = sum_xy - sum_x * sum_y / n
    variance_x = sum_x2 - sum_x**2 / n
    variance_y = sum_y2 - sum_y**2 / n
    with np.errstate(divide="ignore", invalid="ignore"):
        correlations = covariance / np.sqrt(variance_x * variance_y)
        positive_means = sum_xy / sum_y
        negative_means = (sum_x - sum_xy) / (n - sum_y)
        mean_differences = positive_means - negative_means
    return _quantile_interval(correlations), _quantile_interval(mean_differences)


def _adjusted_task_bootstrap(
    rows: Sequence[ScoreRow],
    x_residual: np.ndarray,
    y_residual: np.ndarray,
    *,
    draws: int,
    seed: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    by_task: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        by_task[row.task_id].append(index)
    tasks = sorted(by_task)
    task_stats = np.asarray(
        [
            (
                float(x_residual[indices] @ x_residual[indices]),
                float(y_residual[indices] @ y_residual[indices]),
                float(x_residual[indices] @ y_residual[indices]),
            )
            for indices in (by_task[task] for task in tasks)
        ],
        dtype=float,
    )
    rng = np.random.default_rng(seed)
    selected = rng.integers(0, len(tasks), size=(draws, len(tasks)))
    sampled = task_stats[selected].sum(axis=1)
    sum_x2, sum_y2, sum_xy = sampled.T
    with np.errstate(divide="ignore", invalid="ignore"):
        slopes_per_ten = 10.0 * sum_xy / sum_x2
        correlations = sum_xy / np.sqrt(sum_x2 * sum_y2)
    return _quantile_interval(slopes_per_ten), _quantile_interval(correlations)


def _within_stratum_permutation_p(
    rows: Sequence[ScoreRow],
    x_residual: np.ndarray,
    y_residual: np.ndarray,
    *,
    draws: int,
    seed: int,
) -> float:
    groups: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[_stratum_key(row)].append(index)
    observed = float(x_residual @ y_residual)
    rng = np.random.default_rng(seed)
    permuted = np.zeros(draws, dtype=float)
    for indices_value in groups.values():
        indices = np.asarray(indices_value, dtype=int)
        if len(indices) < 2:
            continue
        permutations = np.asarray(list(itertools.permutations(range(len(indices)))))
        possible = x_residual[indices][permutations] @ y_residual[indices]
        choices = rng.integers(0, len(possible), size=draws)
        permuted += possible[choices]
    extreme = int(np.sum(np.abs(permuted) >= abs(observed) - 1e-15))
    return (extreme + 1) / (draws + 1)


def _association(
    rows: Sequence[ScoreRow],
    x_values: np.ndarray,
    y_values: np.ndarray,
    *,
    bootstrap_draws: int,
    permutation_draws: int,
    seed: int,
) -> dict[str, float | int]:
    positives = int(np.sum(y_values))
    negatives = len(rows) - positives
    if positives == 0 or negatives == 0:
        raise ValueError("association requires both RH outcomes")
    raw_r = _correlation(x_values, y_values)
    positive_mean = float(np.mean(x_values[y_values == 1]))
    negative_mean = float(np.mean(x_values[y_values == 0]))
    raw_r_ci, mean_difference_ci = _raw_task_bootstrap(
        rows,
        x_values,
        y_values,
        draws=bootstrap_draws,
        seed=seed,
    )

    x_residual = _residualize(rows, x_values)
    y_residual = _residualize(rows, y_values)
    sum_x2 = float(x_residual @ x_residual)
    sum_y2 = float(y_residual @ y_residual)
    sum_xy = float(x_residual @ y_residual)
    adjusted_slope = 10.0 * sum_xy / sum_x2 if sum_x2 > 0 else math.nan
    adjusted_r = (
        sum_xy / math.sqrt(sum_x2 * sum_y2)
        if sum_x2 > 0 and sum_y2 > 0
        else math.nan
    )
    slope_ci, adjusted_r_ci = _adjusted_task_bootstrap(
        rows,
        x_residual,
        y_residual,
        draws=bootstrap_draws,
        seed=seed + 1,
    )
    permutation_p = _within_stratum_permutation_p(
        rows,
        x_residual,
        y_residual,
        draws=permutation_draws,
        seed=seed + 2,
    )
    strata: dict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        strata[_stratum_key(row)].append(index)
    informative_strata = sum(
        len(indices) > 1
        and float(np.var(x_values[indices])) > 0
        and float(np.var(y_values[indices])) > 0
        for indices in strata.values()
    )
    return {
        "n": len(rows),
        "rh_positive": positives,
        "rh_rate": positives / len(rows),
        "score_mean_rh_positive": positive_mean,
        "score_mean_rh_negative": negative_mean,
        "score_mean_difference": positive_mean - negative_mean,
        "score_mean_difference_ci_low": mean_difference_ci[0],
        "score_mean_difference_ci_high": mean_difference_ci[1],
        "raw_point_biserial_r": raw_r,
        "raw_r_ci_low": raw_r_ci[0],
        "raw_r_ci_high": raw_r_ci[1],
        "adjusted_r": adjusted_r,
        "adjusted_r_ci_low": adjusted_r_ci[0],
        "adjusted_r_ci_high": adjusted_r_ci[1],
        "adjusted_risk_difference_per_10_points": adjusted_slope,
        "adjusted_risk_difference_ci_low": slope_ci[0],
        "adjusted_risk_difference_ci_high": slope_ci[1],
        "within_cell_permutation_p": permutation_p,
        "strata": len(strata),
        "informative_strata": informative_strata,
    }


def _bh_adjust(p_values: Sequence[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=lambda index: p_values[index])
    adjusted = [1.0] * count
    running = 1.0
    for rank_index in range(count - 1, -1, -1):
        index = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _association_rows(
    rows: Sequence[ScoreRow],
    detectors: Sequence[str],
    *,
    bootstrap_draws: int,
    permutation_draws: int,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for scope in SCOPES:
        scoped = [row for row in rows if scope.keep(row)]
        for detector in detectors:
            valid = [row for row in scoped if row.outcomes[detector] is not None]
            y_values = np.asarray(
                [int(row.outcomes[detector]) for row in valid],
                dtype=float,
            )
            for feature in FEATURES:
                x_values = np.asarray([feature.value(row) for row in valid], dtype=float)
                result = _association(
                    valid,
                    x_values,
                    y_values,
                    bootstrap_draws=bootstrap_draws,
                    permutation_draws=permutation_draws,
                    seed=_stable_seed(scope.name, detector, feature.name),
                )
                results.append(
                    {
                        "scope": scope.name,
                        "scope_label": scope.label,
                        "detector": detector,
                        "feature": feature.name,
                        "feature_label": feature.label,
                        **result,
                    }
                )
    for detector in detectors:
        indices = [
            index for index, row in enumerate(results) if row["detector"] == detector
        ]
        adjusted = _bh_adjust(
            [float(results[index]["within_cell_permutation_p"]) for index in indices]
        )
        for index, q_value in zip(indices, adjusted, strict=True):
            results[index]["detector_family_bh_q"] = q_value
    return results


def _round_rows(
    rows: Sequence[ScoreRow],
    detectors: Sequence[str],
    *,
    bootstrap_draws: int,
    permutation_draws: int,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for study in ("full", "semi"):
        scoped = [row for row in rows if row.study == study]
        for detector in detectors:
            valid = [row for row in scoped if row.outcomes[detector] is not None]
            y_values = np.asarray(
                [int(row.outcomes[detector]) for row in valid],
                dtype=float,
            )
            family_indices: list[int] = []
            for round_index in range(11):
                x_values = np.asarray(
                    [row.scores[round_index] for row in valid],
                    dtype=float,
                )
                result = _association(
                    valid,
                    x_values,
                    y_values,
                    bootstrap_draws=bootstrap_draws,
                    permutation_draws=permutation_draws,
                    seed=_stable_seed("round", study, detector, round_index),
                )
                family_indices.append(len(results))
                results.append(
                    {
                        "study": study,
                        "detector": detector,
                        "round": round_index,
                        **result,
                    }
                )
            adjusted = _bh_adjust(
                [
                    float(results[index]["within_cell_permutation_p"])
                    for index in family_indices
                ]
            )
            for index, q_value in zip(family_indices, adjusted, strict=True):
                results[index]["round_family_bh_q"] = q_value
    return results


def _score_band_rows(
    rows: Sequence[ScoreRow],
    detectors: Sequence[str],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for study in ("full", "semi"):
        for policy in ("all", "static", "prospective"):
            scoped = [
                row
                for row in rows
                if row.study == study
                and (policy == "all" or row.rubric_policy == policy)
            ]
            for detector in detectors:
                valid = [row for row in scoped if row.outcomes[detector] is not None]
                for band, lower, upper in SCORE_BANDS:
                    selected = [
                        row for row in valid if lower <= row.scores[-1] < upper
                    ]
                    positives = sum(int(row.outcomes[detector]) for row in selected)
                    results.append(
                        {
                            "study": study,
                            "rubric_policy": policy,
                            "detector": detector,
                            "score_band": band,
                            "score_lower": lower,
                            "score_upper_exclusive": upper,
                            "n": len(selected),
                            "rh_positive": positives,
                            "rh_rate": positives / len(selected) if selected else math.nan,
                            "mean_final_score": (
                                float(np.mean([row.scores[-1] for row in selected]))
                                if selected
                                else math.nan
                            ),
                        }
                    )
    return results


def _write_csv(path: Path, rows: Sequence[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _assignment_rows(
    rows: Sequence[ScoreRow],
    detectors: Sequence[str],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        output.append(
            {
                "study": row.study,
                "experiment_id": row.experiment_id,
                "task_id": row.task_id,
                "replicate": row.replicate,
                "prompt": row.prompt,
                "rubric_policy": row.rubric_policy,
                "condition_id": row.condition_id,
                "assignment_id": row.assignment_id,
                **{
                    f"score_r{round_index:02d}": score
                    for round_index, score in enumerate(row.scores)
                },
                "baseline_score": row.scores[0],
                "final_score": row.scores[-1],
                "score_gain": row.scores[-1] - row.scores[0],
                "mean_post_score": float(np.mean(row.scores[1:])),
                **{f"rh_{detector}": row.outcomes[detector] for detector in detectors},
            }
        )
    return output


def _find_association(
    rows: Sequence[dict[str, object]],
    *,
    scope: str,
    detector: str,
    feature: str,
) -> dict[str, object]:
    matches = [
        row
        for row in rows
        if row["scope"] == scope
        and row["detector"] == detector
        and row["feature"] == feature
    ]
    if len(matches) != 1:
        raise ValueError(f"association lookup failed: {scope}, {detector}, {feature}")
    return matches[0]


def _plot(
    output_dir: Path,
    association_rows: Sequence[dict[str, object]],
    round_rows: Sequence[dict[str, object]],
    band_rows: Sequence[dict[str, object]],
    detector_models: Sequence[str],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    figure, axes = plt.subplots(2, 2, figsize=(12.5, 9.0))

    ax = axes[0, 0]
    selected_bands = [
        row
        for row in band_rows
        if row["study"] == "full"
        and row["rubric_policy"] == "all"
        and row["detector"] == MAJORITY_DETECTOR
    ]
    x_positions = np.arange(len(selected_bands))
    rates = [100.0 * float(row["rh_rate"]) for row in selected_bands]
    bars = ax.bar(x_positions, rates, color="#4472C4")
    ax.set_xticks(x_positions, [str(row["score_band"]) for row in selected_bands])
    ax.set_ylabel("Majority RH rate (%)")
    ax.set_xlabel("Final rubric score")
    ax.set_title("A. Full feedback: descriptive score bands")
    for bar, row in zip(bars, selected_bands, strict=True):
        if int(row["n"]) > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.25,
                f"{int(row['rh_positive'])}/{int(row['n'])}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax = axes[0, 1]
    scope_order = [
        "full",
        "full-static",
        "full-prospective",
        "semi",
        "semi-static",
        "semi-prospective",
    ]
    effects = [
        _find_association(
            association_rows,
            scope=scope,
            detector=MAJORITY_DETECTOR,
            feature="final_score",
        )
        for scope in scope_order
    ]
    y_positions = np.arange(len(effects))
    estimates = np.asarray(
        [100.0 * float(row["adjusted_risk_difference_per_10_points"]) for row in effects]
    )
    lowers = np.asarray(
        [100.0 * float(row["adjusted_risk_difference_ci_low"]) for row in effects]
    )
    uppers = np.asarray(
        [100.0 * float(row["adjusted_risk_difference_ci_high"]) for row in effects]
    )
    ax.errorbar(
        estimates,
        y_positions,
        xerr=np.vstack([estimates - lowers, uppers - estimates]),
        fmt="o",
        color="#C00000",
        capsize=3,
    )
    ax.axvline(0.0, color="black", linewidth=0.8)
    ax.set_yticks(y_positions, [str(row["scope_label"]) for row in effects])
    ax.invert_yaxis()
    ax.set_xlabel("Adjusted RH-rate change per +10 score points (pp)")
    ax.set_title("B. Majority RH association by protocol")

    ax = axes[1, 0]
    for study, color in (("full", "#C00000"), ("semi", "#4472C4")):
        selected = [
            row
            for row in round_rows
            if row["study"] == study and row["detector"] == MAJORITY_DETECTOR
        ]
        rounds = np.asarray([int(row["round"]) for row in selected])
        estimates = np.asarray(
            [100.0 * float(row["adjusted_risk_difference_per_10_points"]) for row in selected]
        )
        lowers = np.asarray(
            [100.0 * float(row["adjusted_risk_difference_ci_low"]) for row in selected]
        )
        uppers = np.asarray(
            [100.0 * float(row["adjusted_risk_difference_ci_high"]) for row in selected]
        )
        ax.plot(rounds, estimates, marker="o", color=color, label=study.title())
        ax.fill_between(rounds, lowers, uppers, color=color, alpha=0.15)
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_xticks(range(11))
    ax.set_xlabel("Revision boundary (0 is baseline)")
    ax.set_ylabel("Adjusted RH-rate change per +10 score points (pp)")
    ax.set_title("C. Majority association across rounds")
    ax.legend(frameon=False)

    ax = axes[1, 1]
    detector_order = [MAJORITY_DETECTOR, ANY_DETECTOR, *detector_models]
    effects = [
        _find_association(
            association_rows,
            scope="full",
            detector=detector,
            feature="final_score",
        )
        for detector in detector_order
    ]
    y_positions = np.arange(len(effects))
    estimates = np.asarray(
        [100.0 * float(row["adjusted_risk_difference_per_10_points"]) for row in effects]
    )
    lowers = np.asarray(
        [100.0 * float(row["adjusted_risk_difference_ci_low"]) for row in effects]
    )
    uppers = np.asarray(
        [100.0 * float(row["adjusted_risk_difference_ci_high"]) for row in effects]
    )
    labels = ["Majority", "Any detector", *detector_models]
    ax.errorbar(
        estimates,
        y_positions,
        xerr=np.vstack([estimates - lowers, uppers - estimates]),
        fmt="o",
        color="#7030A0",
        capsize=3,
    )
    ax.axvline(0.0, color="black", linewidth=0.8)
    ax.set_yticks(y_positions, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Adjusted RH-rate change per +10 score points (pp)")
    ax.set_title("D. Full-feedback detector sensitivity")

    figure.suptitle("Rubric score and reward-hacking detection", fontsize=14)
    figure.tight_layout()
    figure.savefig(output_dir / "rubric_score_rh.png", dpi=180)
    figure.savefig(output_dir / "rubric_score_rh.pdf")
    plt.close(figure)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for tables and figures.",
    )
    parser.add_argument("--bootstrap-draws", type=int, default=5_000)
    parser.add_argument("--permutation-draws", type=int, default=10_000)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.bootstrap_draws < 100 or args.permutation_draws < 100:
        raise ValueError("use at least 100 bootstrap and permutation draws")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows, detector_models = _load_rows()
    detectors = [MAJORITY_DETECTOR, ANY_DETECTOR, *detector_models]
    association_rows = _association_rows(
        rows,
        detectors,
        bootstrap_draws=args.bootstrap_draws,
        permutation_draws=args.permutation_draws,
    )
    round_rows = _round_rows(
        rows,
        [MAJORITY_DETECTOR, ANY_DETECTOR],
        bootstrap_draws=args.bootstrap_draws,
        permutation_draws=args.permutation_draws,
    )
    band_rows = _score_band_rows(rows, [MAJORITY_DETECTOR, ANY_DETECTOR])

    _write_csv(output_dir / "assignment_scores.csv", _assignment_rows(rows, detectors))
    _write_csv(output_dir / "score_associations.csv", association_rows)
    _write_csv(output_dir / "round_associations.csv", round_rows)
    _write_csv(output_dir / "final_score_bands.csv", band_rows)
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "studies": [spec.experiment_id for spec in STUDIES],
                "assignment_count": len(rows),
                "detectors": detectors,
                "features": [feature.name for feature in FEATURES],
                "bootstrap_draws": args.bootstrap_draws,
                "permutation_draws": args.permutation_draws,
                "associations": association_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _plot(output_dir, association_rows, round_rows, band_rows, detector_models)

    primary = _find_association(
        association_rows,
        scope="full",
        detector=MAJORITY_DETECTOR,
        feature="final_score",
    )
    print(
        "full majority: "
        f"n={primary['n']}, RH={primary['rh_positive']}, "
        f"raw_r={float(primary['raw_point_biserial_r']):.3f}, "
        "adjusted_pp_per_10="
        f"{100.0 * float(primary['adjusted_risk_difference_per_10_points']):.2f}, "
        f"p={float(primary['within_cell_permutation_p']):.4f}"
    )


if __name__ == "__main__":
    main()
