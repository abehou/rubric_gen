from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean

import matplotlib.pyplot as plt
import numpy as np


FIGURE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FIGURE_ROOT.parents[1]
EXPERIMENT_PATH = PROJECT_ROOT / "experiments/biomnibench-results20-user-simulator-full.yaml"
EXPERIMENT_ID = "biomnibench-da-factorial-r10-4f4d5d178756"
SUMMARY_PATH = PROJECT_ROOT / "runs/detections" / EXPERIMENT_ID / "summary.json"
CSV_PATH = FIGURE_ROOT / "evaluation_by_condition.csv"
QUALITY_STEM = FIGURE_ROOT / "quality_gains_by_condition"
GAPS_STEM = FIGURE_ROOT / "generalization_gaps_by_condition"
STRONG_PAIRWISE_STEM = FIGURE_ROOT / "strong_vs_pairwise_by_condition"

RUBRIC_ORDER = ("fixed", "offline_elicitation", "online_elicitation")
RUBRIC_LABELS = {
    "fixed": "Static rubric",
    "offline_elicitation": "Offline elicited",
    "online_elicitation": "Online elicited",
}
FEEDBACK_ORDER = ("full", "user-simulator")
FEEDBACK_LABELS = {
    "full": "Full feedback",
    "user-simulator": "User simulator",
}
COLORS = {
    "full": "#0072B2",
    "user-simulator": "#CC79A7",
}
METRICS = (
    "original_rubric_weak_gain",
    "strong_original_rubric_gain",
    "selected_rubric_gain",
    "holdout_rubric_gain",
    "rubric_free_absolute_score_gain",
    "pairwise_preference_score",
    "strong_original_final_score",
    "weak_to_strong_rubric_gap",
    "selected_to_holdout_rubric_gap",
    "strong_original_to_holistic_gap",
)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260901


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_summary() -> dict[str, object]:
    if not EXPERIMENT_PATH.is_file():
        raise RuntimeError(f"experiment is missing: {EXPERIMENT_PATH}")
    value = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    if (
        value.get("kind") != "rubric-gen-revision-evaluation"
        or value.get("status") != "completed"
        or value.get("experiment_id") != EXPERIMENT_ID
    ):
        raise RuntimeError("evaluation source is not the completed r10 report")
    coverage = value.get("assignment_coverage")
    assignments = value.get("assignments")
    if (
        not isinstance(coverage, dict)
        or coverage.get("configured_assignment_count") != 360
        or coverage.get("evaluated_assignment_count") != 317
        or coverage.get("excluded_assignment_count") != 43
        or not isinstance(assignments, list)
        or len(assignments) != 317
    ):
        raise RuntimeError("evaluation source has unexpected assignment coverage")
    return value


def _condition(assignment: dict[str, object]) -> tuple[str, str]:
    rubric = str(assignment["rubric_policy"])
    suffix = {
        "fixed": "-static",
        "offline_elicitation": "-offline-rubric",
        "online_elicitation": "-online-rubric",
    }.get(rubric)
    condition_id = str(assignment["condition_id"])
    if suffix is None or not condition_id.endswith(suffix):
        raise RuntimeError(f"condition and rubric policy disagree: {condition_id}")
    feedback = condition_id[: -len(suffix)]
    if feedback not in FEEDBACK_ORDER:
        raise RuntimeError(f"unexpected feedback condition: {condition_id}")
    return rubric, feedback


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"evaluation metric is not numeric: {label}")
    result = float(value)
    if not np.isfinite(result):
        raise RuntimeError(f"evaluation metric is not finite: {label}")
    return result


def load_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    assignments = summary["assignments"]
    assert isinstance(assignments, list)
    rows: list[dict[str, object]] = []
    for assignment_value in assignments:
        if not isinstance(assignment_value, dict):
            raise RuntimeError("evaluation assignment is invalid")
        rubric, feedback = _condition(assignment_value)
        outcomes = assignment_value.get("outcomes")
        artifacts = assignment_value.get("artifacts")
        reference_scores = assignment_value.get("reference_scores")
        if not all(isinstance(value, dict) for value in (outcomes, artifacts, reference_scores)):
            raise RuntimeError("evaluation assignment has invalid metric groups")
        assert isinstance(outcomes, dict)
        assert isinstance(artifacts, dict)
        assert isinstance(reference_scores, dict)
        initial = artifacts.get("initial")
        final = artifacts.get("final")
        if not isinstance(initial, dict) or not isinstance(final, dict):
            raise RuntimeError("evaluation assignment has invalid artifacts")
        selected_scores = reference_scores.get("selected")
        holdout_scores = reference_scores.get("holdout")
        if not isinstance(selected_scores, dict) or not isinstance(holdout_scores, dict):
            raise RuntimeError("evaluation assignment has invalid reference scores")
        selected_final = selected_scores.get("final")
        holdout_final = holdout_scores.get("final")
        if not isinstance(selected_final, dict) or not isinstance(holdout_final, dict):
            raise RuntimeError("evaluation assignment has invalid final reference scores")
        strong_final = _finite(final.get("strong_original_rubric_score"), "final strong original")
        weak_final = _finite(final.get("weak_original_rubric_score"), "final weak original")
        selected_final_score = _finite(selected_final.get("mean"), "final selected rubric")
        holdout_final_score = _finite(holdout_final.get("mean"), "final held-out rubric")
        holistic_final = _finite(final.get("rubric_free_absolute_score"), "final rubric-free absolute")
        strong_gain = strong_final - _finite(
            initial.get("strong_original_rubric_score"), "initial strong original"
        )
        weak_gain = _finite(outcomes.get("original_rubric_weak_gain"), "original_rubric_weak_gain")
        selected_gain = _finite(outcomes.get("selected_rubric_gain"), "selected_rubric_gain")
        holdout_gain = _finite(outcomes.get("holdout_rubric_gain"), "holdout_rubric_gain")
        holistic_gain = _finite(
            outcomes.get("rubric_free_absolute_score_gain"),
            "rubric_free_absolute_score_gain",
        )
        row: dict[str, object] = {
            "assignment_id": str(assignment_value["assignment_id"]),
            "task_id": str(assignment_value["task_id"]),
            "replicate": int(assignment_value["replicate"]),
            "rubric_type": rubric,
            "feedback_type": feedback,
            "original_rubric_weak_gain": weak_gain,
            "strong_original_rubric_gain": strong_gain,
            "selected_rubric_gain": selected_gain,
            "holdout_rubric_gain": holdout_gain,
            "rubric_free_absolute_score_gain": holistic_gain,
            "pairwise_preference_score": _finite(
                outcomes.get("pairwise_preference_score"),
                "pairwise_preference_score",
            ),
            "strong_original_final_score": strong_final,
            "weak_to_strong_rubric_gap": weak_final - strong_final,
            "selected_to_holdout_rubric_gap": selected_final_score - holdout_final_score,
            "strong_original_to_holistic_gap": strong_final - holistic_final,
        }
        rows.append(row)
    rows.sort(key=lambda row: str(row["assignment_id"]))
    return rows


def _cluster_summary(
    rows: list[dict[str, object]],
    metric: str,
    *,
    seed_offset: int,
) -> tuple[float, float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task_id"])].append(float(row[metric]))
    if len(by_task) != 20 or any(not 1 <= len(values) <= 3 for values in by_task.values()):
        raise RuntimeError("condition cell does not cover 20 tasks with one to three replicates")
    task_means = np.asarray(
        [fmean(by_task[task]) for task in sorted(by_task)],
        dtype=float,
    )
    rng = np.random.default_rng(BOOTSTRAP_SEED + seed_offset)
    samples = rng.choice(
        task_means,
        size=(BOOTSTRAP_REPLICATES, len(task_means)),
        replace=True,
    )
    lower, upper = np.quantile(samples.mean(axis=1), (0.025, 0.975))
    return float(task_means.mean()), float(lower), float(upper)


def aggregate(rows: list[dict[str, object]], source_sha256: str) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["rubric_type"]), str(row["feedback_type"]))].append(row)
    expected = {
        (rubric, feedback)
        for rubric in RUBRIC_ORDER
        for feedback in FEEDBACK_ORDER
    }
    if set(grouped) != expected:
        raise RuntimeError("evaluation does not contain the complete 2-by-3 design")

    result: list[dict[str, object]] = []
    seed_offset = 0
    for rubric in RUBRIC_ORDER:
        for feedback in FEEDBACK_ORDER:
            group = grouped[(rubric, feedback)]
            record: dict[str, object] = {
                "source_summary_sha256": source_sha256,
                "rubric_type": rubric,
                "feedback_type": feedback,
                "assignment_count": len(group),
                "task_count": len({str(row["task_id"]) for row in group}),
            }
            for metric in METRICS:
                mean, lower, upper = _cluster_summary(
                    group,
                    metric,
                    seed_offset=seed_offset,
                )
                seed_offset += 1
                record[metric] = mean
                record[f"{metric}_clustered_95_lower"] = lower
                record[f"{metric}_clustered_95_upper"] = upper
            result.append(record)
    return result


def write_csv(records: list[dict[str, object]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def _draw_metric(
    axis: plt.Axes,
    records: list[dict[str, object]],
    metric: str,
    *,
    title: str,
    ylabel: str,
    scale: float = 1.0,
    baseline: float = 0.0,
) -> None:
    by_key = {
        (str(record["rubric_type"]), str(record["feedback_type"])): record
        for record in records
    }
    width = 0.34
    centers = np.arange(len(RUBRIC_ORDER), dtype=float)
    interval_values = [baseline]
    for feedback, offset in zip(FEEDBACK_ORDER, (-width / 2, width / 2), strict=True):
        selected = [by_key[(rubric, feedback)] for rubric in RUBRIC_ORDER]
        values = np.asarray([scale * float(row[metric]) for row in selected])
        lower = np.asarray([scale * float(row[f"{metric}_clustered_95_lower"]) for row in selected])
        upper = np.asarray([scale * float(row[f"{metric}_clustered_95_upper"]) for row in selected])
        positions = centers + offset
        bars = axis.bar(
            positions,
            values,
            width=width,
            yerr=np.vstack((values - lower, upper - values)),
            capsize=3,
            error_kw={"elinewidth": 1.0, "capthick": 1.0, "ecolor": "#333333"},
            color=COLORS[feedback],
            label=FEEDBACK_LABELS[feedback],
            edgecolor="white",
            linewidth=0.8,
            zorder=2,
        )
        interval_values.extend(lower.tolist())
        interval_values.extend(upper.tolist())
        for bar, value, row in zip(bars, values, selected, strict=True):
            text = f"{value:.1f}%" if scale == 100 else f"{value:+.1f}"
            axis.annotate(
                f"{text}\nn={row['assignment_count']}",
                (bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 5 if value >= baseline else -5),
                textcoords="offset points",
                ha="center",
                va="bottom" if value >= baseline else "top",
                fontsize=7.5,
                zorder=3,
            )
    axis.axhline(baseline, color="#333333", linewidth=0.9)
    axis.set_xticks(centers, [RUBRIC_LABELS[item] for item in RUBRIC_ORDER])
    axis.set_title(title, fontsize=11, fontweight="bold")
    axis.set_ylabel(ylabel)
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    low = min(interval_values)
    high = max(interval_values)
    padding = max(2.0, 0.22 * (high - low))
    axis.set_ylim(low - padding, high + padding)


def plot_quality(records: list[dict[str, object]]) -> None:
    figure, axes = plt.subplots(2, 2, figsize=(15.5, 10.2))
    specifications = (
        ("strong_original_rubric_gain", "Strong original-rubric gain", "Final − initial score (points)", 1.0, 0.0),
        ("holdout_rubric_gain", "Held-out-rubric gain", "Final − initial score (points)", 1.0, 0.0),
        ("rubric_free_absolute_score_gain", "Rubric-free holistic gain", "Final − initial score (points)", 1.0, 0.0),
        ("pairwise_preference_score", "Pairwise preference for final", "Final preference (%)", 100.0, 50.0),
    )
    for axis, (metric, title, ylabel, scale, baseline) in zip(axes.flat, specifications, strict=True):
        _draw_metric(
            axis,
            records,
            metric,
            title=title,
            ylabel=ylabel,
            scale=scale,
            baseline=baseline,
        )
    handles, labels = axes[0][0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.93), ncol=2, frameon=False)
    figure.suptitle(
        "BioMNIBench Results20: strong, held-out, and holistic evaluation",
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )
    figure.text(
        0.5,
        0.012,
        "Bars show task-balanced means. Whiskers are task-clustered 95% bootstrap intervals; "
        "each task mean uses available completed replicates.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    figure.subplots_adjust(top=0.86, bottom=0.10, left=0.07, right=0.99, hspace=0.32, wspace=0.18)
    figure.savefig(QUALITY_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(QUALITY_STEM.with_suffix(".pdf"), facecolor="white")


def plot_gaps(records: list[dict[str, object]]) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(18.0, 6.6))
    specifications = (
        (
            "weak_to_strong_rubric_gap",
            "Final weak-to-strong original-rubric gap",
            "Final weak original − strong original (points)",
        ),
        (
            "selected_to_holdout_rubric_gap",
            "Final strong selected-to-held-out gap",
            "Final selected rubric − held-out rubric (points)",
        ),
        (
            "strong_original_to_holistic_gap",
            "Final strong original-to-rubric-free gap",
            "Final strong original − rubric-free (points)",
        ),
    )
    for axis, (metric, title, ylabel) in zip(axes, specifications, strict=True):
        _draw_metric(axis, records, metric, title=title, ylabel=ylabel)
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.89), ncol=2, frameon=False)
    figure.suptitle(
        "BioMNIBench Results20: final-artifact evaluation gaps by condition",
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )
    figure.text(
        0.5,
        0.012,
        "All gaps use only final-artifact scores. Positive values mean the first score exceeds the second score. "
        "Whiskers are task-clustered 95% bootstrap intervals.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    figure.subplots_adjust(top=0.78, bottom=0.16, left=0.055, right=0.995, wspace=0.22)
    figure.savefig(GAPS_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(GAPS_STEM.with_suffix(".pdf"), facecolor="white")


def plot_strong_vs_pairwise(records: list[dict[str, object]]) -> None:
    figure, axis = plt.subplots(figsize=(10.5, 7.5))
    markers = {
        "fixed": "o",
        "offline_elicitation": "s",
        "online_elicitation": "^",
    }
    for record in records:
        rubric = str(record["rubric_type"])
        feedback = str(record["feedback_type"])
        x = float(record["strong_original_final_score"])
        x_lower = float(record["strong_original_final_score_clustered_95_lower"])
        x_upper = float(record["strong_original_final_score_clustered_95_upper"])
        y = 100 * float(record["pairwise_preference_score"])
        y_lower = 100 * float(record["pairwise_preference_score_clustered_95_lower"])
        y_upper = 100 * float(record["pairwise_preference_score_clustered_95_upper"])
        axis.errorbar(
            x,
            y,
            xerr=np.asarray([[x - x_lower], [x_upper - x]]),
            yerr=np.asarray([[y - y_lower], [y_upper - y]]),
            marker=markers[rubric],
            markersize=9,
            color=COLORS[feedback],
            markeredgecolor="white",
            markeredgewidth=0.8,
            capsize=3,
            elinewidth=1.0,
            linestyle="none",
            label=f"{FEEDBACK_LABELS[feedback]} · {RUBRIC_LABELS[rubric]}",
            zorder=3,
        )
    axis.axhline(50, color="#555555", linewidth=0.9, linestyle="--")
    axis.set_xlabel("Final strong original-rubric score (points)")
    axis.set_ylabel("Pairwise preference for final (%)")
    axis.set_title(
        "BioMNIBench Results20: final strong score vs pairwise preference",
        fontsize=14,
        fontweight="bold",
    )
    axis.grid(color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.legend(frameon=False, fontsize=9, ncol=2)
    figure.text(
        0.5,
        0.012,
        "Points are task-balanced condition means. Whiskers are task-clustered 95% bootstrap intervals.\n"
        "Pairwise preference compares final with initial. The axes have different units, so their values are not subtracted.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    figure.subplots_adjust(bottom=0.14, left=0.11, right=0.98, top=0.91)
    figure.savefig(STRONG_PAIRWISE_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(STRONG_PAIRWISE_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    summary = _load_summary()
    records = aggregate(load_rows(summary), _sha256(SUMMARY_PATH))
    write_csv(records)
    plot_quality(records)
    plot_gaps(records)
    plot_strong_vs_pairwise(records)


if __name__ == "__main__":
    main()
