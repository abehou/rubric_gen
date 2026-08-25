from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "direct_rh_detection_by_condition.csv"
OUTPUT_STEM = ROOT / "direct_rh_detection_by_condition"

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


def load_rows() -> dict[tuple[str, str], dict[str, int | float | str]]:
    with DATA_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    parsed: dict[tuple[str, str], dict[str, int | float | str]] = {}
    for row in rows:
        key = (row["rubric_type"], row["feedback_type"])
        if key in parsed:
            raise ValueError(f"duplicate result cell: {key}")
        detected = int(row["detected"])
        evaluated = int(row["evaluated"])
        abstained = int(row["abstained"])
        rate = float(row["detection_rate"])
        if detected > evaluated or evaluated + abstained != 9:
            raise ValueError(f"invalid result cell: {key}")
        if abs(rate - detected / evaluated) > 1e-12:
            raise ValueError(f"rate disagrees with counts: {key}")
        parsed[key] = {
            **row,
            "detected": detected,
            "evaluated": evaluated,
            "abstained": abstained,
            "detection_rate": rate,
        }
    expected = {
        (rubric, feedback)
        for rubric in RUBRIC_ORDER
        for feedback in FEEDBACK_ORDER
    }
    if set(parsed) != expected:
        raise ValueError("source data do not contain the complete 3-by-4 design")
    return parsed


def main() -> None:
    rows = load_rows()
    figure, axis = plt.subplots(figsize=(9.2, 6.2))
    x_positions = list(range(len(RUBRIC_ORDER)))
    bottoms = [0] * len(RUBRIC_ORDER)

    for feedback in FEEDBACK_ORDER:
        heights = [
            int(rows[(rubric, feedback)]["detected"])
            for rubric in RUBRIC_ORDER
        ]
        bars = axis.bar(
            x_positions,
            heights,
            width=0.64,
            bottom=bottoms,
            label=FEEDBACK_LABELS[feedback],
            color=COLORS[feedback],
            edgecolor="white",
            linewidth=1.2,
        )
        for index, bar in enumerate(bars):
            rubric = RUBRIC_ORDER[index]
            row = rows[(rubric, feedback)]
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                bottoms[index] + heights[index] / 2,
                f"{row['detected']}/{row['evaluated']}",
                ha="center",
                va="center",
                color="white",
                fontsize=9.5,
                fontweight="bold",
            )
            bottoms[index] += heights[index]

    for index, rubric in enumerate(RUBRIC_ORDER):
        detected = sum(
            int(rows[(rubric, feedback)]["detected"])
            for feedback in FEEDBACK_ORDER
        )
        evaluated = sum(
            int(rows[(rubric, feedback)]["evaluated"])
            for feedback in FEEDBACK_ORDER
        )
        abstained = sum(
            int(rows[(rubric, feedback)]["abstained"])
            for feedback in FEEDBACK_ORDER
        )
        label = f"{detected}/{evaluated} detected\n{100 * detected / evaluated:.1f}%"
        if abstained:
            label += f" · {abstained} abstained"
        axis.text(
            index,
            detected + 0.22,
            label,
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    axis.set_title(
        "Direct reward-hacking detections by rubric and feedback\n"
        "BioMNIBench development factorial · earlier elicitation protocol",
        fontsize=14,
        fontweight="bold",
        pad=58,
    )
    axis.set_ylabel("Detected assignments (stacked by feedback type)")
    axis.set_xticks(x_positions, [RUBRIC_LABELS[value] for value in RUBRIC_ORDER])
    axis.set_ylim(0, 8.6)
    axis.set_yticks(range(0, 9))
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, 1.13),
        ncol=4,
        frameon=False,
        title="Feedback type",
    )
    figure.text(
        0.5,
        0.015,
        "Segment labels show detected/evaluated. The direct panel used the "
        "any-detect rule across three judges.\n"
        "Each cell had nine assignments. Three offline/full panels abstained "
        "and are excluded from that rate.",
        ha="center",
        va="bottom",
        fontsize=8.7,
        color="#444444",
    )
    figure.subplots_adjust(top=0.72, bottom=0.18, left=0.11, right=0.98)
    figure.savefig(OUTPUT_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(OUTPUT_STEM.with_suffix(".pdf"), facecolor="white")


if __name__ == "__main__":
    main()
