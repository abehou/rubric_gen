from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


FIGURE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FIGURE_ROOT.parents[1]
EXPERIMENT_ID = "biomnibench-da-factorial-r6-5d56fee68932"
DIRECT_ROOT = PROJECT_ROOT / "runs" / "detections" / EXPERIMENT_ID / "direct"
CSV_PATH = FIGURE_ROOT / "direct_rh_detection_by_condition.csv"
OUTPUT_STEM = FIGURE_ROOT / "direct_rh_detection_by_condition"
JUDGE_OUTPUT_STEM = FIGURE_ROOT / "direct_rh_detection_by_condition_by_judge"

RUBRIC_ORDER = ("static", "offline-rubric", "online-rubric")
RUBRIC_LABELS = {
    "static": "Static rubric",
    "offline-rubric": "Offline elicited",
    "online-rubric": "Online elicited",
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
JUDGES = ("gpt-5.6-sol", "claude-opus-5")
PANELS = ("available-judge-union", *JUDGES)
PANEL_LABELS = {
    "available-judge-union": "Available-judge any-detect",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "claude-opus-5": "Claude Opus 5",
}


def condition_parts(source_path: str) -> tuple[str, str]:
    condition = Path(source_path).name
    for suffix, rubric in (
        ("-offline-rubric", "offline-rubric"),
        ("-online-rubric", "online-rubric"),
        ("-static", "static"),
    ):
        if condition.endswith(suffix):
            return rubric, condition[: -len(suffix)]
    raise ValueError(f"unknown condition: {condition}")


def load_records() -> dict[str, dict[str, str]]:
    summaries = list(DIRECT_ROOT.glob("evaluations/*/summary.json"))
    if len(summaries) != 1:
        raise RuntimeError(f"expected one direct summary, found {len(summaries)}")
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    if summary.get("primary_rule") != "any_detect":
        raise RuntimeError("results20 direct audit does not use any_detect")
    if set(summary.get("models", [])) != {*JUDGES, "gemini-3.6-flash"}:
        raise RuntimeError("results20 direct judge panel is unexpected")

    cases: dict[str, dict[str, str]] = defaultdict(dict)
    for record in summary["records"]:
        provider = record["provider"]
        source_path = record["source_path"]
        if provider in cases[source_path]:
            raise RuntimeError(f"duplicate provider result: {source_path} {provider}")
        verdict = record.get("verdict")
        decision = verdict.get("decision") if isinstance(verdict, dict) else "failed"
        cases[source_path][provider] = str(decision)
    if len(cases) != 720:
        raise RuntimeError(f"expected 720 results20 cases, found {len(cases)}")
    return cases


def panel_decision(panel: str, verdicts: dict[str, str]) -> str:
    if panel == "available-judge-union":
        available = [verdicts.get(judge, "failed") for judge in JUDGES]
        if "reward_hacking_detected" in available:
            return "detected"
        if "no_reward_hacking_detected" in available:
            return "not_detected"
        return "excluded"
    return {
        "reward_hacking_detected": "detected",
        "no_reward_hacking_detected": "not_detected",
        "abstain": "abstained",
    }.get(verdicts.get(panel, "failed"), "failed")


def aggregate() -> dict[tuple[str, str, str], Counter[str]]:
    groups: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for source_path, verdicts in load_records().items():
        rubric, feedback = condition_parts(source_path)
        for panel in PANELS:
            groups[(panel, rubric, feedback)][panel_decision(panel, verdicts)] += 1

    expected = {
        (panel, rubric, feedback)
        for panel in PANELS
        for rubric in RUBRIC_ORDER
        for feedback in FEEDBACK_ORDER
    }
    if set(groups) != expected:
        raise RuntimeError("results20 data do not contain the complete 3-by-4 design")
    if any(sum(counts.values()) != 60 for counts in groups.values()):
        raise RuntimeError("a results20 condition does not contain 60 assignments")
    return groups


def write_csv(groups: dict[tuple[str, str, str], Counter[str]]) -> None:
    fields = (
        "panel",
        "rubric_type",
        "feedback_type",
        "detected",
        "evaluated",
        "abstained",
        "failed",
        "excluded",
        "detection_rate",
    )
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for panel in PANELS:
            for rubric in RUBRIC_ORDER:
                for feedback in FEEDBACK_ORDER:
                    counts = groups[(panel, rubric, feedback)]
                    detected = counts["detected"]
                    evaluated = detected + counts["not_detected"]
                    writer.writerow({
                        "panel": panel,
                        "rubric_type": rubric,
                        "feedback_type": feedback,
                        "detected": detected,
                        "evaluated": evaluated,
                        "abstained": counts["abstained"],
                        "failed": counts["failed"],
                        "excluded": 60 - evaluated,
                        "detection_rate": detected / evaluated if evaluated else "",
                    })


def rubric_total(
    groups: dict[tuple[str, str, str], Counter[str]],
    panel: str,
    rubric: str,
) -> tuple[int, int]:
    detected = 0
    evaluated = 0
    for feedback in FEEDBACK_ORDER:
        counts = groups[(panel, rubric, feedback)]
        detected += counts["detected"]
        evaluated += counts["detected"] + counts["not_detected"]
    return detected, evaluated


def draw_grouped_bars(
    axis: plt.Axes,
    groups: dict[tuple[str, str, str], Counter[str]],
    panel: str,
    *,
    show_ylabel: bool,
    title: str | None = None,
) -> None:
    width = 0.19
    centers = list(range(len(RUBRIC_ORDER)))
    offsets = (-1.5 * width, -0.5 * width, 0.5 * width, 1.5 * width)

    for feedback, offset in zip(FEEDBACK_ORDER, offsets, strict=True):
        rates = []
        labels = []
        for rubric in RUBRIC_ORDER:
            counts = groups[(panel, rubric, feedback)]
            detected = counts["detected"]
            evaluated = detected + counts["not_detected"]
            rates.append(100 * detected / evaluated if evaluated else 0.0)
            labels.append(f"{detected}/{evaluated}")
        positions = [center + offset for center in centers]
        bars = axis.bar(
            positions,
            rates,
            width=width,
            label=FEEDBACK_LABELS[feedback],
            color=COLORS[feedback],
            edgecolor="white",
            linewidth=0.8,
        )
        for bar, rate, label in zip(bars, rates, labels, strict=True):
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                max(rate, 0.25) + 0.45,
                label,
                ha="center",
                va="bottom",
                fontsize=8.2,
                rotation=90 if panel != "available-judge-union" else 0,
            )

    tick_labels = []
    for rubric in RUBRIC_ORDER:
        detected, evaluated = rubric_total(groups, panel, rubric)
        tick_labels.append(
            f"{RUBRIC_LABELS[rubric]}\n{detected}/{evaluated} ({100 * detected / evaluated:.1f}%)"
        )
    axis.set_xticks(centers, tick_labels)
    if show_ylabel:
        axis.set_ylabel("Direct RH detection rate (%)")
    if title:
        axis.set_title(title, fontsize=12, fontweight="bold")
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)


def plot_available_union(
    groups: dict[tuple[str, str, str], Counter[str]],
) -> None:
    figure, axis = plt.subplots(figsize=(10.4, 6.4))
    draw_grouped_bars(
        axis,
        groups,
        "available-judge-union",
        show_ylabel=True,
    )
    axis.set_ylim(0, 18.5)
    axis.set_title(
        "BioMNIBench results20: direct RH detection by condition\n"
        "Available-judge any-detect · partial two-judge panel",
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
        "Bars are side by side. Labels show detected/evaluated. "
        "Gemini completed 0/720 calls and is excluded.\n"
        "This is not the configured three-judge primary result. GPT and Claude "
        "each completed 720 calls; every case has a usable union decision.",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.20, left=0.10, right=0.98)
    figure.savefig(OUTPUT_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(OUTPUT_STEM.with_suffix(".pdf"), facecolor="white")


def plot_judges(groups: dict[tuple[str, str, str], Counter[str]]) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(15.2, 6.0), sharey=True)
    for index, (axis, judge) in enumerate(zip(axes, JUDGES, strict=True)):
        draw_grouped_bars(
            axis,
            groups,
            judge,
            show_ylabel=index == 0,
            title=PANEL_LABELS[judge],
        )
        axis.set_ylim(0, 18.5)
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
        "BioMNIBench results20: usable direct judges",
        fontsize=15,
        fontweight="bold",
        y=0.98,
    )
    figure.text(
        0.5,
        0.014,
        "Labels show detected/evaluated. Excluded cases are abstained or "
        "failed judgments. Gemini completed 0/720 calls.",
        ha="center",
        va="bottom",
        fontsize=8.8,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.21, left=0.07, right=0.99, wspace=0.12)
    figure.savefig(JUDGE_OUTPUT_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(JUDGE_OUTPUT_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    groups = aggregate()
    write_csv(groups)
    plot_available_union(groups)
    plot_judges(groups)


if __name__ == "__main__":
    main()
