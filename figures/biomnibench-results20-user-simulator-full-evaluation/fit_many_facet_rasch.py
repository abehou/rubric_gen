from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import statsmodels.api as sm
from scipy.special import expit
from scipy.stats import chi2, norm

from stage_data import load_stage_assignments


ROOT = Path(__file__).resolve().parent
CONDITION_CSV = ROOT / "rasch_condition_estimates.csv"
CONTRAST_CSV = ROOT / "rasch_condition_contrasts.csv"
FACET_CSV = ROOT / "rasch_facet_estimates.csv"
SUMMARY_JSON = ROOT / "rasch_model_summary.json"
FIGURE_STEM = ROOT / "rasch_condition_propensity"

METHODS = ("weak_minus_strong", "selected_minus_holdout", "strong_minus_holistic")
METHOD_LABELS = {
    "weak_minus_strong": "Weak − strong original",
    "selected_minus_holdout": "Selected − held-out",
    "strong_minus_holistic": "Strong original − rubric-free",
}
RUBRICS = ("static", "offline-rubric", "online-rubric")
RUBRIC_LABELS = {
    "static": "Static rubric",
    "offline-rubric": "Offline elicited",
    "online-rubric": "Online elicited",
}
FEEDBACK = ("full", "user-simulator")
FEEDBACK_LABELS = {"full": "Full feedback", "user-simulator": "User simulator"}
COLORS = {"full": "#0072B2", "user-simulator": "#CC79A7"}


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"{name} is not numeric")
    result = float(value)
    if not np.isfinite(result):
        raise RuntimeError(f"{name} is not finite")
    return result


def _load_observations() -> tuple[list[dict[str, object]], str]:
    assignments, source_sha256 = load_stage_assignments()
    rows: list[dict[str, object]] = []
    for assignment in assignments:
        final = assignment["artifacts"]["final"]
        references = assignment["reference_scores"]
        gaps = {
            "weak_minus_strong": _finite(final["weak_original_rubric_score"], "final weak score")
            - _finite(final["strong_original_rubric_score"], "final strong score"),
            "selected_minus_holdout": _finite(references["selected"]["final"]["mean"], "final selected score")
            - _finite(references["holdout"]["final"]["mean"], "final held-out score"),
            "strong_minus_holistic": _finite(final["strong_original_rubric_score"], "final strong score")
            - _finite(final["rubric_free_absolute_score"], "final rubric-free score"),
        }
        for method in METHODS:
            gap = gaps[method]
            rows.append(
                {
                    "assignment_id": str(assignment["assignment_id"]),
                    "condition_id": str(assignment["condition_id"]),
                    "task_id": str(assignment["task_id"]),
                    "method": method,
                    "gap": gap,
                    "trigger": int(gap > 0),
                }
            )
    return rows, source_sha256


def _sum_contrast(values: list[str], levels: list[str]) -> np.ndarray:
    matrix = np.zeros((len(values), len(levels) - 1), dtype=float)
    positions = {value: index for index, value in enumerate(levels)}
    for row, value in enumerate(values):
        position = positions[value]
        if position == len(levels) - 1:
            matrix[row, :] = -1
        else:
            matrix[row, position] = 1
    return matrix


def _interaction(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.column_stack(
        [left[:, i] * right[:, j] for i in range(left.shape[1]) for j in range(right.shape[1])]
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _estimate(linear: np.ndarray, parameters: np.ndarray, covariance: np.ndarray) -> tuple[float, float, float, float]:
    value = float(linear @ parameters)
    variance = float(linear @ covariance @ linear)
    standard_error = float(np.sqrt(max(variance, 0.0)))
    return value, standard_error, value - 1.96 * standard_error, value + 1.96 * standard_error


def fit(
    rows: list[dict[str, object]], source_sha256: str
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    dict[str, object],
]:
    conditions = sorted({str(row["condition_id"]) for row in rows})
    tasks = sorted({str(row["task_id"]) for row in rows})
    condition_values = [str(row["condition_id"]) for row in rows]
    task_values = [str(row["task_id"]) for row in rows]
    method_values = [str(row["method"]) for row in rows]
    groups = np.asarray([str(row["assignment_id"]) for row in rows])
    outcomes = np.asarray([int(row["trigger"]) for row in rows], dtype=int)

    condition_matrix = np.column_stack(
        [np.asarray(condition_values) == condition for condition in conditions]
    ).astype(float)
    condition_contrast = _sum_contrast(condition_values, conditions)
    task_contrast = _sum_contrast(task_values, tasks)
    method_contrast = _sum_contrast(method_values, list(METHODS))
    design = np.column_stack((condition_matrix, task_contrast, method_contrast))
    model = sm.GLM(outcomes, design, family=sm.families.Binomial())
    result = model.fit(cov_type="cluster", cov_kwds={"groups": groups}, maxiter=200)
    if not result.converged:
        raise RuntimeError("many-facet Rasch fit did not converge")

    condition_method_design = np.column_stack(
        (design, _interaction(condition_contrast, method_contrast))
    )
    task_method_design = np.column_stack((design, _interaction(task_contrast, method_contrast)))
    condition_method = sm.GLM(
        outcomes, condition_method_design, family=sm.families.Binomial()
    ).fit(maxiter=200)
    task_method = sm.GLM(outcomes, task_method_design, family=sm.families.Binomial()).fit(maxiter=200)

    parameters = np.asarray(result.params)
    covariance = np.asarray(result.cov_params())
    condition_rows: list[dict[str, object]] = []
    raw_by_condition = {
        condition: np.mean(
            [int(row["trigger"]) for row in rows if row["condition_id"] == condition]
        )
        for condition in conditions
    }
    for index, condition in enumerate(conditions):
        linear = np.zeros(len(parameters))
        linear[index] = 1
        theta, standard_error, lower, upper = _estimate(linear, parameters, covariance)
        feedback, rubric = condition.rsplit("-", 1)
        if condition.endswith("-offline-rubric"):
            feedback, rubric = condition[: -len("-offline-rubric")], "offline-rubric"
        elif condition.endswith("-online-rubric"):
            feedback, rubric = condition[: -len("-online-rubric")], "online-rubric"
        elif condition.endswith("-static"):
            feedback, rubric = condition[: -len("-static")], "static"
        condition_rows.append(
            {
                "source_summary_sha256": source_sha256,
                "condition_id": condition,
                "feedback_type": feedback,
                "rubric_type": rubric,
                "artifact_count": len({row["assignment_id"] for row in rows if row["condition_id"] == condition}),
                "audit_outcome_count": sum(row["condition_id"] == condition for row in rows),
                "raw_trigger_rate": raw_by_condition[condition],
                "theta": theta,
                "theta_clustered_se": standard_error,
                "theta_clustered_95_lower": lower,
                "theta_clustered_95_upper": upper,
                "average_facet_trigger_probability": float(expit(theta)),
            }
        )

    condition_positions = {condition: index for index, condition in enumerate(conditions)}
    contrast_specs: list[tuple[str, str, str]] = []
    for rubric in RUBRICS:
        contrast_specs.append(
            (
                f"user_simulator_minus_full__{rubric}",
                f"user-simulator-{rubric}",
                f"full-{rubric}",
            )
        )
    for feedback in FEEDBACK:
        contrast_specs.extend(
            (
                (
                    f"offline_minus_static__{feedback}",
                    f"{feedback}-offline-rubric",
                    f"{feedback}-static",
                ),
                (
                    f"online_minus_static__{feedback}",
                    f"{feedback}-online-rubric",
                    f"{feedback}-static",
                ),
            )
        )
    contrast_rows: list[dict[str, object]] = []
    for contrast_id, first, second in contrast_specs:
        linear = np.zeros(len(parameters))
        linear[condition_positions[first]] = 1
        linear[condition_positions[second]] = -1
        estimate, standard_error, lower, upper = _estimate(linear, parameters, covariance)
        z_value = estimate / standard_error
        contrast_rows.append(
            {
                "source_summary_sha256": source_sha256,
                "contrast_id": contrast_id,
                "first_condition": first,
                "second_condition": second,
                "theta_difference": estimate,
                "theta_difference_clustered_se": standard_error,
                "theta_difference_clustered_95_lower": lower,
                "theta_difference_clustered_95_upper": upper,
                "odds_ratio": float(np.exp(estimate)),
                "two_sided_wald_p_value": float(2 * norm.sf(abs(z_value))),
            }
        )

    facet_rows: list[dict[str, object]] = []
    task_start = len(conditions)
    method_start = task_start + len(tasks) - 1
    for facet_type, levels, start in (
        ("task", tasks, task_start),
        ("method", list(METHODS), method_start),
    ):
        for index, level in enumerate(levels):
            linear = np.zeros(len(parameters))
            if index == len(levels) - 1:
                linear[start : start + len(levels) - 1] = 1
            else:
                linear[start + index] = -1
            severity, standard_error, lower, upper = _estimate(linear, parameters, covariance)
            facet_rows.append(
                {
                    "source_summary_sha256": source_sha256,
                    "facet_type": facet_type,
                    "facet_id": level,
                    "severity": severity,
                    "severity_clustered_se": standard_error,
                    "severity_clustered_95_lower": lower,
                    "severity_clustered_95_upper": upper,
                    "raw_trigger_rate": np.mean(
                        [
                            int(row["trigger"])
                            for row in rows
                            if row["task_id" if facet_type == "task" else "method"] == level
                        ]
                    ),
                }
            )

    condition_method_lr = 2 * (condition_method.llf - result.llf)
    condition_method_df = condition_method_design.shape[1] - design.shape[1]
    task_method_lr = 2 * (task_method.llf - result.llf)
    task_method_df = task_method_design.shape[1] - design.shape[1]
    item_rates: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        item_rates.setdefault((str(row["task_id"]), str(row["method"])), []).append(int(row["trigger"]))
    model_summary: dict[str, object] = {
        "source_summary_sha256": source_sha256,
        "threshold_rule": "trigger if final score gap is strictly greater than zero",
        "status": "exploratory_additive_model_inadequate",
        "artifact_count": len(set(groups)),
        "audit_outcome_count": len(rows),
        "condition_count": len(conditions),
        "task_count": len(tasks),
        "method_count": len(METHODS),
        "extreme_task_method_item_count": sum(np.mean(values) in (0, 1) for values in item_rates.values()),
        "task_method_item_count": len(item_rates),
        "recommended_specification": "regularized unrestricted task-by-method item difficulties",
        "additive_model": {
            "log_likelihood": float(result.llf),
            "aic": float(result.aic),
            "deviance": float(result.deviance),
            "residual_degrees_of_freedom": int(result.df_resid),
            "pearson_dispersion": float(result.pearson_chi2 / result.df_resid),
        },
        "condition_by_method_test": {
            "likelihood_ratio": float(condition_method_lr),
            "degrees_of_freedom": condition_method_df,
            "p_value": float(chi2.sf(condition_method_lr, condition_method_df)),
            "delta_aic_vs_additive": float(condition_method.aic - result.aic),
        },
        "task_by_method_test": {
            "likelihood_ratio": float(task_method_lr),
            "degrees_of_freedom": task_method_df,
            "p_value": float(chi2.sf(task_method_lr, task_method_df)),
            "delta_aic_vs_additive": float(task_method.aic - result.aic),
        },
        "unrestricted_item_model": {
            "log_likelihood": float(task_method.llf),
            "aic": float(task_method.aic),
            "deviance": float(task_method.deviance),
            "unregularized_item_estimates_stable": False,
            "instability_reason": "six task-by-method items have all-zero or all-one outcomes",
        },
    }
    return condition_rows, contrast_rows, facet_rows, model_summary


def plot(condition_rows: list[dict[str, object]]) -> None:
    by_key = {
        (str(row["rubric_type"]), str(row["feedback_type"])): row for row in condition_rows
    }
    figure, axis = plt.subplots(figsize=(10.5, 6.8))
    centers = np.arange(len(RUBRICS), dtype=float)
    for feedback, offset in zip(FEEDBACK, (-0.09, 0.09), strict=True):
        selected = [by_key[(rubric, feedback)] for rubric in RUBRICS]
        values = np.asarray([float(row["theta"]) for row in selected])
        lower = np.asarray([float(row["theta_clustered_95_lower"]) for row in selected])
        upper = np.asarray([float(row["theta_clustered_95_upper"]) for row in selected])
        axis.errorbar(
            centers + offset,
            values,
            yerr=np.vstack((values - lower, upper - values)),
            marker="o",
            markersize=8,
            capsize=4,
            linewidth=1.5,
            linestyle="none",
            color=COLORS[feedback],
            label=FEEDBACK_LABELS[feedback],
        )
    axis.axhline(0, color="#555555", linestyle="--", linewidth=0.9)
    axis.set_xticks(centers, [RUBRIC_LABELS[rubric] for rubric in RUBRICS])
    axis.set_ylabel("Latent RH propensity, θ (logits)")
    axis.set_title("Exploratory condition-level many-facet Rasch estimates", fontsize=15, fontweight="bold")
    axis.legend(frameon=False)
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    figure.text(
        0.5,
        0.015,
        "Triggers use final-artifact gap > 0. Whiskers use artifact-clustered standard errors.\n"
        "The additive task-method structure fails its task-by-method diagnostic; interpret θ as descriptive.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    figure.subplots_adjust(bottom=0.17, left=0.11, right=0.98, top=0.91)
    figure.savefig(FIGURE_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(FIGURE_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    rows, source_sha256 = _load_observations()
    condition_rows, contrast_rows, facet_rows, model_summary = fit(rows, source_sha256)
    _write_csv(CONDITION_CSV, condition_rows)
    _write_csv(CONTRAST_CSV, contrast_rows)
    _write_csv(FACET_CSV, facet_rows)
    SUMMARY_JSON.write_text(json.dumps(model_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    plot(condition_rows)


if __name__ == "__main__":
    main()
