from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean

import matplotlib.pyplot as plt
import numpy as np

from rubric_gen.submission_revision.experiment import load_experiment


FIGURE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FIGURE_ROOT.parents[1]
EXPERIMENT_PATH = PROJECT_ROOT / "experiments" / "biomnibench-results20.yaml"
CSV_PATH = FIGURE_ROOT / "generalization_gap_changes_by_condition.csv"
WEAK_OUTPUT_STEM = FIGURE_ROOT / "weak_to_strong_gap_change_by_condition"
WEAK_INITIAL_OUTPUT_STEM = FIGURE_ROOT / "weak_to_strong_initial_gap_by_condition"
WEAK_FINAL_OUTPUT_STEM = FIGURE_ROOT / "weak_to_strong_final_gap_by_condition"
STRONG_OUTPUT_STEM = FIGURE_ROOT / "strong_to_rubric_free_gap_change_by_condition"

RUBRIC_ORDER = ("static", "offline-rubric", "online-rubric")
RUBRIC_LABELS = {
    "static": "Static rubric",
    "offline-rubric": "Offline elicited",
    "online-rubric": "Online elicited",
}
RUBRIC_POLICIES = {
    "fixed": "static",
    "offline_elicitation": "offline-rubric",
    "online_elicitation": "online-rubric",
}
FEEDBACK_ORDER = ("full", "semi", "score-only", "user-simulator")
FEEDBACK_LABELS = {
    "full": "Full",
    "semi": "Semi",
    "score-only": "Score only",
    "user-simulator": "User simulator",
}
COLORS = {
    "full": "#0072B2",
    "semi": "#E69F00",
    "score-only": "#009E73",
    "user-simulator": "#CC79A7",
}
METRICS = (
    "weak_to_strong_initial_gap",
    "weak_to_strong_final_gap",
    "weak_to_strong_gap_change",
    "original_to_rubric_free_gap_change",
    "active_to_original_gap_change",
    "selected_to_rubric_free_gap_change",
)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260827


def condition_parts(condition_id: str, rubric_policy: str) -> tuple[str, str]:
    rubric = RUBRIC_POLICIES.get(rubric_policy)
    if rubric is None:
        raise RuntimeError(f"unknown rubric policy: {rubric_policy}")
    suffix = "-static" if rubric == "static" else f"-{rubric}"
    if not condition_id.endswith(suffix):
        raise RuntimeError(
            f"condition and rubric policy disagree: {condition_id} {rubric_policy}"
        )
    feedback = condition_id[: -len(suffix)]
    if feedback not in FEEDBACK_ORDER:
        raise RuntimeError(f"unknown feedback type: {feedback}")
    return rubric, feedback


def load_rows() -> list[dict[str, object]]:
    experiment = load_experiment(EXPERIMENT_PATH)
    summary_path = Path(str(experiment.dag["detect"]["output_dir"])) / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("experiment_id") != experiment.experiment_id:
        raise RuntimeError("gap summary has the wrong experiment ID")
    if summary.get("status") != "completed":
        raise RuntimeError("gap summary is not complete")
    assignments = summary.get("assignments")
    if not isinstance(assignments, list) or len(assignments) != 720:
        raise RuntimeError("gap summary does not contain 720 assignments")

    rows: list[dict[str, object]] = []
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise RuntimeError("gap summary contains an invalid assignment")
        rubric, feedback = condition_parts(
            str(assignment["condition_id"]),
            str(assignment["rubric_policy"]),
        )
        component_changes = assignment["component_changes"]
        rubric_changes = assignment["rubric_diagnostic_changes"]
        artifacts = assignment["artifacts"]
        if not isinstance(component_changes, dict) or not isinstance(
            rubric_changes, dict
        ) or not isinstance(artifacts, dict):
            raise RuntimeError("gap summary contains invalid change records")
        initial = artifacts.get("initial")
        final = artifacts.get("final")
        if not isinstance(initial, dict) or not isinstance(final, dict):
            raise RuntimeError("gap summary contains invalid artifacts")
        initial_components = initial.get("components")
        final_components = final.get("components")
        if not isinstance(initial_components, dict) or not isinstance(
            final_components, dict
        ):
            raise RuntimeError("gap summary contains invalid artifact components")
        initial_gap = float(initial_components["verifier_exploitation"])
        final_gap = float(final_components["verifier_exploitation"])
        gap_change = float(component_changes["verifier_exploitation"])
        if not np.isclose(final_gap - initial_gap, gap_change, atol=1e-9, rtol=0):
            raise RuntimeError("weak-to-strong gap change disagrees with artifacts")
        row: dict[str, object] = {
            "assignment_id": str(assignment["assignment_id"]),
            "task_id": str(assignment["task_id"]),
            "replicate": int(assignment["replicate"]),
            "rubric_type": rubric,
            "feedback_type": feedback,
            "weak_to_strong_initial_gap": initial_gap,
            "weak_to_strong_final_gap": final_gap,
            "weak_to_strong_gap_change": gap_change,
            "original_to_rubric_free_gap_change": float(
                component_changes["original_rubric_gap"]
            ),
            "active_to_original_gap_change": float(
                rubric_changes["active_to_original"]
            ),
            "selected_to_rubric_free_gap_change": float(
                rubric_changes["selected_rubric_minus_rubric_free_absolute_score"]
            ),
        }
        if not all(np.isfinite(float(row[metric])) for metric in METRICS):
            raise RuntimeError("gap summary contains a non-finite change")
        rows.append(row)

    rows.sort(key=lambda row: str(row["assignment_id"]))
    matched_initial: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in rows:
        matched_initial[(
            str(row["task_id"]),
            int(row["replicate"]),
        )].append(float(row["weak_to_strong_initial_gap"]))
    if any(
        len(values) != 12
        or not np.allclose(values, values[0], atol=1e-9, rtol=0)
        for values in matched_initial.values()
    ):
        raise RuntimeError(
            "matched initial weak-to-strong gaps are not equal across conditions"
        )
    return rows


def cluster_interval(
    rows: list[dict[str, object]],
    metric: str,
    *,
    seed_offset: int,
) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task_id"])].append(float(row[metric]))
    if len(by_task) != 20 or any(len(values) != 3 for values in by_task.values()):
        raise RuntimeError("condition cell is not balanced over 20 tasks and 3 replicates")
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
    return float(lower), float(upper)


def aggregate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["rubric_type"]), str(row["feedback_type"]))].append(row)
    expected = {
        (rubric, feedback)
        for rubric in RUBRIC_ORDER
        for feedback in FEEDBACK_ORDER
    }
    if set(grouped) != expected or any(len(group) != 60 for group in grouped.values()):
        raise RuntimeError("gap summary does not contain a balanced 3-by-4 design")

    aggregates: list[dict[str, object]] = []
    seed_offset = 0
    for rubric in RUBRIC_ORDER:
        for feedback in FEEDBACK_ORDER:
            group = grouped[(rubric, feedback)]
            record: dict[str, object] = {
                "rubric_type": rubric,
                "feedback_type": feedback,
                "assignment_count": len(group),
                "task_count": len({str(row["task_id"]) for row in group}),
            }
            for metric in METRICS:
                mean = fmean(float(row[metric]) for row in group)
                lower, upper = cluster_interval(
                    group,
                    metric,
                    seed_offset=seed_offset,
                )
                seed_offset += 1
                record[metric] = mean
                record[f"{metric}_clustered_95_lower"] = lower
                record[f"{metric}_clustered_95_upper"] = upper
            aggregates.append(record)
    return aggregates


def write_csv(aggregates: list[dict[str, object]]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(aggregates[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(aggregates)


def draw_grouped_bars(
    axis: plt.Axes,
    aggregates: list[dict[str, object]],
    metric: str,
    *,
    ylabel: str,
    title: str | None = None,
) -> None:
    by_key = {
        (str(row["rubric_type"]), str(row["feedback_type"])): row
        for row in aggregates
    }
    width = 0.19
    centers = np.arange(len(RUBRIC_ORDER), dtype=float)
    offsets = (-1.5 * width, -0.5 * width, 0.5 * width, 1.5 * width)
    interval_extremes: list[float] = [0.0]

    for feedback, offset in zip(FEEDBACK_ORDER, offsets, strict=True):
        values = np.asarray(
            [float(by_key[(rubric, feedback)][metric]) for rubric in RUBRIC_ORDER]
        )
        lower = np.asarray(
            [
                float(by_key[(rubric, feedback)][f"{metric}_clustered_95_lower"])
                for rubric in RUBRIC_ORDER
            ]
        )
        upper = np.asarray(
            [
                float(by_key[(rubric, feedback)][f"{metric}_clustered_95_upper"])
                for rubric in RUBRIC_ORDER
            ]
        )
        positions = centers + offset
        bars = axis.bar(
            positions,
            values,
            width=width,
            yerr=np.vstack((values - lower, upper - values)),
            capsize=3.2,
            error_kw={"elinewidth": 1.0, "capthick": 1.0, "ecolor": "#333333"},
            label=FEEDBACK_LABELS[feedback],
            color=COLORS[feedback],
            edgecolor="white",
            linewidth=0.8,
            zorder=2,
        )
        interval_extremes.extend(lower.tolist())
        interval_extremes.extend(upper.tolist())
        for bar, value in zip(bars, values, strict=True):
            axis.annotate(
                f"{value:+.1f}",
                (bar.get_x() + bar.get_width() / 2, value),
                xytext=(0, 5 if value >= 0 else -5),
                textcoords="offset points",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=8.2,
                fontweight="bold",
                zorder=3,
            )

    axis.axhline(0, color="#333333", linewidth=0.9)
    axis.set_xticks(
        centers,
        [f"{RUBRIC_LABELS[rubric]}\nn=240" for rubric in RUBRIC_ORDER],
    )
    axis.set_ylabel(ylabel)
    if title is not None:
        axis.set_title(title, fontsize=12, fontweight="bold")
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    lower_limit = min(interval_extremes)
    upper_limit = max(interval_extremes)
    padding = max(1.5, 0.18 * (upper_limit - lower_limit))
    axis.set_ylim(lower_limit - padding, upper_limit + padding)


def plot_weak_to_strong(aggregates: list[dict[str, object]]) -> None:
    figure, axis = plt.subplots(figsize=(10.4, 6.4))
    draw_grouped_bars(
        axis,
        aggregates,
        "weak_to_strong_gap_change",
        ylabel="Change in weak − strong gap (points)",
    )
    axis.set_title(
        "BioMNIBench results20: weak-to-strong gap change by condition\n"
        "Δ(W − A) · final minus initial",
        fontsize=14,
        fontweight="bold",
        pad=54,
    )
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.12),
        ncol=4,
        frameon=False,
        title="Feedback type",
    )
    figure.text(
        0.5,
        0.014,
        "Bars show 60-assignment means. Whiskers are task-clustered 95% "
        "bootstrap intervals from 20 tasks and 3 replicates.\n"
        "Negative values mean the weak-judge advantage shrank. "
        "Strong = mean(GPT-5.6 Sol, Claude Opus 5); Gemini was unavailable.",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.20, left=0.10, right=0.98)
    figure.savefig(WEAK_OUTPUT_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(WEAK_OUTPUT_STEM.with_suffix(".pdf"), facecolor="white")


def plot_weak_to_strong_artifact(
    aggregates: list[dict[str, object]],
    *,
    metric: str,
    artifact_label: str,
    output_stem: Path,
) -> None:
    figure, axis = plt.subplots(figsize=(10.4, 6.4))
    draw_grouped_bars(
        axis,
        aggregates,
        metric,
        ylabel="Weak − strong gap (points)",
    )
    axis.set_title(
        "BioMNIBench results20: weak-to-strong gap by condition\n"
        f"{artifact_label} artifact · W − A",
        fontsize=14,
        fontweight="bold",
        pad=54,
    )
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.12),
        ncol=4,
        frameon=False,
        title="Feedback type",
    )
    figure.text(
        0.5,
        0.014,
        "Bars show 60-assignment means. Whiskers are task-clustered 95% "
        "bootstrap intervals from 20 tasks and 3 replicates.\n"
        "Positive values mean the weak judge scored higher. "
        "Strong = mean(GPT-5.6 Sol, Claude Opus 5); Gemini was unavailable.",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.20, left=0.10, right=0.98)
    figure.savefig(output_stem.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(output_stem.with_suffix(".pdf"), facecolor="white")


def plot_strong_to_rubric_free(aggregates: list[dict[str, object]]) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(19.2, 6.3), sharey=True)
    draw_grouped_bars(
        axes[0],
        aggregates,
        "original_to_rubric_free_gap_change",
        ylabel="Change in strong − rubric-free gap (points)",
        title="Original common rubric: Δ(A − Q)",
    )
    draw_grouped_bars(
        axes[1],
        aggregates,
        "active_to_original_gap_change",
        ylabel="",
        title="Active-rubric drift: Δ(B − A)",
    )
    draw_grouped_bars(
        axes[2],
        aggregates,
        "selected_to_rubric_free_gap_change",
        ylabel="",
        title="Selected common rubric: Δ(S − Q)",
    )
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.89),
        ncol=4,
        frameon=False,
        title="Feedback type",
    )
    figure.suptitle(
        "BioMNIBench results20: strong-to-rubric-free gap change by condition",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )
    figure.text(
        0.5,
        0.015,
        "Bars show 60-assignment means. Whiskers are task-clustered 95% "
        "bootstrap intervals from 20 tasks and 3 replicates.\n"
        "The original and selected rubrics are common rulers. The active panel "
        "shows ruler drift and does not measure absolute artifact quality.",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.22, left=0.07, right=0.99, wspace=0.16)
    figure.savefig(STRONG_OUTPUT_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(STRONG_OUTPUT_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    aggregates = aggregate(load_rows())
    write_csv(aggregates)
    plot_weak_to_strong(aggregates)
    plot_weak_to_strong_artifact(
        aggregates,
        metric="weak_to_strong_initial_gap",
        artifact_label="Initial",
        output_stem=WEAK_INITIAL_OUTPUT_STEM,
    )
    plot_weak_to_strong_artifact(
        aggregates,
        metric="weak_to_strong_final_gap",
        artifact_label="Final",
        output_stem=WEAK_FINAL_OUTPUT_STEM,
    )
    plot_strong_to_rubric_free(aggregates)


if __name__ == "__main__":
    main()
