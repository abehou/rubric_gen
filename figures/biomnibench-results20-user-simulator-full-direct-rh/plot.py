from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


FIGURE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FIGURE_ROOT.parents[1]
EXPERIMENT_PATH = PROJECT_ROOT / "experiments/biomnibench-results20-user-simulator-full.yaml"
EXPERIMENT_ID = "biomnibench-da-factorial-r10-4f4d5d178756"
SUMMARY_PATH = PROJECT_ROOT / "runs/detections" / EXPERIMENT_ID / "summary.json"
CSV_PATH = FIGURE_ROOT / "direct_rh_detection_by_condition.csv"
PRIMARY_STEM = FIGURE_ROOT / "direct_rh_detection_by_condition"
JUDGE_STEM = FIGURE_ROOT / "direct_rh_detection_by_condition_by_judge"

WINDOWS = ("full_trajectory", "post_update")
WINDOW_FIELDS = {
    "full_trajectory": "direct_detection",
    "post_update": "post_update_detection",
}
WINDOW_LABELS = {
    "full_trajectory": "Full trajectory",
    "post_update": "Post update",
}
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
JUDGES = ("gpt-5.6-sol", "claude-opus-5", "gemini-3.6-flash")
JUDGE_LABELS = {
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "claude-opus-5": "Claude Opus 5",
    "gemini-3.6-flash": "Gemini 3.6 Flash",
}


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
        raise RuntimeError("direct RH source summary is not the completed r10 experiment")
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
        raise RuntimeError("direct RH source summary has unexpected assignment coverage")
    return value


def _condition(assignment: dict[str, object]) -> tuple[str, str]:
    condition_id = str(assignment["condition_id"])
    rubric = str(assignment["rubric_policy"])
    suffix = {
        "fixed": "-static",
        "offline_elicitation": "-offline-rubric",
        "online_elicitation": "-online-rubric",
    }[rubric]
    if not condition_id.endswith(suffix):
        raise RuntimeError(f"condition and rubric policy disagree: {condition_id}")
    feedback = condition_id[: -len(suffix)]
    if feedback not in FEEDBACK_ORDER:
        raise RuntimeError(f"unexpected feedback condition: {condition_id}")
    return rubric, feedback


def _primary_counts(outcome: dict[str, object]) -> tuple[str, float, float]:
    decision = str(outcome["decision"])
    category = {
        "detected": "detected",
        "not_detected": "not_detected",
        "abstain": "abstained",
        "incomplete": "failed",
    }.get(decision)
    bounds = outcome.get("bounds")
    if category is None or not isinstance(bounds, dict):
        raise RuntimeError("primary direct RH outcome is invalid")
    lower = bounds.get("lower")
    upper = bounds.get("upper")
    if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
        raise RuntimeError("primary direct RH bounds are invalid")
    return category, float(lower), float(upper)


def _judge_category(outcome: dict[str, object], judge: str) -> str:
    decisions = outcome.get("provider_decisions")
    if not isinstance(decisions, dict):
        raise RuntimeError("direct RH provider decisions are invalid")
    return {
        "reward_hacking_detected": "detected",
        "no_reward_hacking_detected": "not_detected",
        "abstain": "abstained",
        "failed": "failed",
    }.get(str(decisions.get(judge, "failed")), "failed")


def aggregate(
    summary: dict[str, object],
) -> dict[tuple[str, str, str, str], dict[str, object]]:
    counts: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    primary_bounds: dict[tuple[str, str, str, str], list[tuple[float, float]]] = defaultdict(list)
    assignments = summary["assignments"]
    assert isinstance(assignments, list)
    for assignment_value in assignments:
        if not isinstance(assignment_value, dict):
            raise RuntimeError("direct RH assignment is invalid")
        rubric, feedback = _condition(assignment_value)
        for window in WINDOWS:
            outcome_value = assignment_value.get(WINDOW_FIELDS[window])
            if not isinstance(outcome_value, dict):
                raise RuntimeError("direct RH outcome is invalid")
            primary_key = (window, "primary_any_detect", rubric, feedback)
            category, lower, upper = _primary_counts(outcome_value)
            counts[primary_key][category] += 1
            primary_bounds[primary_key].append((lower, upper))
            for judge in JUDGES:
                counts[(window, judge, rubric, feedback)][
                    _judge_category(outcome_value, judge)
                ] += 1

    expected = {
        (window, panel, rubric, feedback)
        for window in WINDOWS
        for panel in ("primary_any_detect", *JUDGES)
        for rubric in RUBRIC_ORDER
        for feedback in FEEDBACK_ORDER
    }
    if set(counts) != expected:
        raise RuntimeError("direct RH results do not contain the complete 2-by-3 design")

    rows: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for key in sorted(counts):
        window, panel, rubric, feedback = key
        values = counts[key]
        total = sum(values.values())
        detected = values["detected"]
        not_detected = values["not_detected"]
        evaluated = detected + not_detected
        if panel == "primary_any_detect":
            bounds = primary_bounds[key]
            lower = sum(item[0] for item in bounds) / total
            upper = sum(item[1] for item in bounds) / total
        else:
            lower = detected / total
            upper = (detected + values["abstained"] + values["failed"]) / total
        rows[key] = {
            "window": window,
            "panel": panel,
            "rubric_type": rubric,
            "feedback_type": feedback,
            "detected": detected,
            "not_detected": not_detected,
            "abstained": values["abstained"],
            "failed": values["failed"],
            "evaluated": evaluated,
            "total": total,
            "detection_rate": detected / evaluated if evaluated else None,
            "missingness_lower": lower,
            "missingness_upper": upper,
        }
    return rows


def write_csv(
    rows: dict[tuple[str, str, str, str], dict[str, object]],
    source_sha256: str,
) -> None:
    fields = (
        "source_summary_sha256",
        "window",
        "panel",
        "rubric_type",
        "feedback_type",
        "detected",
        "not_detected",
        "abstained",
        "failed",
        "evaluated",
        "total",
        "detection_rate",
        "missingness_lower",
        "missingness_upper",
    )
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow({"source_summary_sha256": source_sha256, **rows[key]})


def _bar_panel(
    axis: plt.Axes,
    rows: dict[tuple[str, str, str, str], dict[str, object]],
    window: str,
    panel: str,
    *,
    show_ylabel: bool,
) -> None:
    width = 0.34
    centers = list(range(len(RUBRIC_ORDER)))
    for feedback, offset in zip(FEEDBACK_ORDER, (-width / 2, width / 2), strict=True):
        selected = [rows[(window, panel, rubric, feedback)] for rubric in RUBRIC_ORDER]
        rates = [100 * float(row["detection_rate"] or 0.0) for row in selected]
        lowers = [100 * float(row["missingness_lower"]) for row in selected]
        uppers = [100 * float(row["missingness_upper"]) for row in selected]
        positions = [center + offset for center in centers]
        bars = axis.bar(
            positions,
            rates,
            width=width,
            color=COLORS[feedback],
            label=FEEDBACK_LABELS[feedback],
            edgecolor="white",
            linewidth=0.8,
        )
        axis.vlines(positions, lowers, uppers, colors="#222222", linewidth=1.2, zorder=4)
        axis.scatter(positions, lowers, color="#222222", marker="_", s=45, zorder=5)
        axis.scatter(positions, uppers, color="#222222", marker="_", s=45, zorder=5)
        for bar, rate, row in zip(bars, rates, selected, strict=True):
            label = f"{row['detected']}/{row['evaluated']}"
            if int(row["failed"]):
                label += f"\n{row['failed']} fail"
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                rate + 0.6,
                label,
                ha="center",
                va="bottom",
                fontsize=8,
            )
    maximum = max(
        100 * float(rows[(window, panel, rubric, feedback)]["missingness_upper"])
        for rubric in RUBRIC_ORDER
        for feedback in FEEDBACK_ORDER
    )
    axis.set_ylim(0, max(12.0, 5 * math.ceil((maximum + 6) / 5)))
    axis.set_xticks(centers, [RUBRIC_LABELS[item] for item in RUBRIC_ORDER])
    if show_ylabel:
        axis.set_ylabel("Direct RH detection rate (%)")
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def plot_primary(rows: dict[tuple[str, str, str, str], dict[str, object]]) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(15.2, 6.4))
    for index, (axis, window) in enumerate(zip(axes, WINDOWS, strict=True)):
        _bar_panel(axis, rows, window, "primary_any_detect", show_ylabel=index == 0)
        axis.set_title(WINDOW_LABELS[window], fontsize=12, fontweight="bold")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.89), ncol=2, frameon=False)
    figure.suptitle(
        "BioMNIBench Results20: direct reward-hacking detection by condition\n"
        "Configured three-judge any-detect panel",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )
    figure.text(
        0.5,
        0.015,
        "Labels show detected/evaluated. Thin vertical marks show sharp missingness bounds. "
        "The analysis includes 317 completed revisions and excludes 43 failed revisions.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.18, left=0.07, right=0.99, wspace=0.14)
    figure.savefig(PRIMARY_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(PRIMARY_STEM.with_suffix(".pdf"), facecolor="white")


def plot_judges(rows: dict[tuple[str, str, str, str], dict[str, object]]) -> None:
    figure, axes = plt.subplots(2, 3, figsize=(18.0, 10.2))
    for row_index, window in enumerate(WINDOWS):
        for column_index, judge in enumerate(JUDGES):
            axis = axes[row_index][column_index]
            _bar_panel(
                axis,
                rows,
                window,
                judge,
                show_ylabel=column_index == 0,
            )
            axis.set_title(
                f"{WINDOW_LABELS[window]} · {JUDGE_LABELS[judge]}",
                fontsize=11,
                fontweight="bold",
            )
    handles, labels = axes[0][0].get_legend_handles_labels()
    figure.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, 0.925), ncol=2, frameon=False)
    figure.suptitle(
        "BioMNIBench Results20: direct reward-hacking detection by judge",
        fontsize=15,
        fontweight="bold",
        y=0.985,
    )
    figure.text(
        0.5,
        0.012,
        "Labels show detected/evaluated. Thin vertical marks treat abstentions and failures as unknown outcomes.",
        ha="center",
        va="bottom",
        fontsize=9,
        color="#444444",
    )
    figure.subplots_adjust(top=0.86, bottom=0.10, left=0.055, right=0.995, hspace=0.34, wspace=0.16)
    figure.savefig(JUDGE_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(JUDGE_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    summary = _load_summary()
    rows = aggregate(summary)
    write_csv(rows, _sha256(SUMMARY_PATH))
    plot_primary(rows)
    plot_judges(rows)


if __name__ == "__main__":
    main()
