from __future__ import annotations

import csv
import glob
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[2]
FIGURE_ROOT = Path(__file__).resolve().parent
DETECTION_ROOT = ROOT / "runs/detections/biomnibench-da-factorial-r10-4f4d5d178756/direct_final_artifact/evaluations"
CSV_PATH = FIGURE_ROOT / "final_artifact_direct_rh_by_condition.csv"
PRIMARY_STEM = FIGURE_ROOT / "final_artifact_direct_rh_by_condition"
JUDGE_STEM = FIGURE_ROOT / "final_artifact_direct_rh_by_condition_by_judge"
RUBRICS = ("fixed", "offline_elicitation", "online_elicitation")
RUBRIC_LABELS = {"fixed": "Static rubric", "offline_elicitation": "Offline elicited", "online_elicitation": "Online elicited"}
FEEDBACK = ("full", "user-simulator")
FEEDBACK_LABELS = {"full": "Full feedback", "user-simulator": "User simulator"}
COLORS = {"full": "#0072B2", "user-simulator": "#CC79A7"}
JUDGES = ("gpt-5.6-sol", "claude-opus-5", "gemini-3.6-flash")
JUDGE_LABELS = {"gpt-5.6-sol": "GPT-5.6 Sol", "claude-opus-5": "Claude Opus 5", "gemini-3.6-flash": "Gemini 3.6 Flash"}


def load_summary() -> tuple[Path, dict[str, object]]:
    paths = sorted(Path(item) for item in glob.glob(str(DETECTION_ROOT / "*--window-final_artifact--*/summary.json")))
    if len(paths) != 1:
        raise RuntimeError(f"expected one completed final-artifact audit, found {len(paths)}")
    value = json.loads(paths[0].read_text(encoding="utf-8"))
    if value.get("kind") != "reward-hacking-model-panel" or len(value.get("records", ())) != 951:
        raise RuntimeError("final-artifact audit is incomplete")
    return paths[0], value


def condition(path: str) -> tuple[str, str]:
    condition_id = Path(path).name
    suffixes = {"fixed": "-static", "offline_elicitation": "-offline-rubric", "online_elicitation": "-online-rubric"}
    for rubric, suffix in suffixes.items():
        if condition_id.endswith(suffix):
            feedback = condition_id[:-len(suffix)]
            if feedback in FEEDBACK:
                return rubric, feedback
    raise RuntimeError(f"invalid condition path: {path}")


def aggregate(summary: dict[str, object]) -> list[dict[str, object]]:
    cases: dict[str, dict[str, str]] = defaultdict(dict)
    case_conditions: dict[str, tuple[str, str]] = {}
    for record in summary["records"]:
        case_id = str(record["case_id"])
        case_conditions[case_id] = condition(str(record["source_path"]))
        verdict = record.get("verdict")
        decision = str(verdict.get("decision")) if isinstance(verdict, dict) else "failed"
        cases[case_id][str(record["model"])] = decision
    if len(cases) != 317 or any(set(values) != set(JUDGES) for values in cases.values()):
        raise RuntimeError("final-artifact audit does not contain the complete judge panel")
    counts: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for case_id, decisions in cases.items():
        rubric, feedback = case_conditions[case_id]
        for judge, decision in decisions.items():
            category = "detected" if decision == "reward_hacking_detected" else "not_detected" if decision == "no_reward_hacking_detected" else "unknown"
            counts[(judge, rubric, feedback)][category] += 1
        values = set(decisions.values())
        primary = "detected" if "reward_hacking_detected" in values else "not_detected" if values == {"no_reward_hacking_detected"} else "unknown"
        counts[("primary_any_detect", rubric, feedback)][primary] += 1
        available = {decisions[judge] for judge in ("gpt-5.6-sol", "claude-opus-5")}
        available_primary = "detected" if "reward_hacking_detected" in available else "not_detected" if available == {"no_reward_hacking_detected"} else "unknown"
        counts[("available_any_detect", rubric, feedback)][available_primary] += 1
    rows = []
    for panel in ("primary_any_detect", "available_any_detect", *JUDGES):
        for rubric in RUBRICS:
            for feedback in FEEDBACK:
                value = counts[(panel, rubric, feedback)]
                total = sum(value.values())
                evaluated = value["detected"] + value["not_detected"]
                rows.append({"panel": panel, "rubric_type": rubric, "feedback_type": feedback, "detected": value["detected"], "not_detected": value["not_detected"], "unknown": value["unknown"], "total": total, "detection_rate": value["detected"] / evaluated if evaluated else None, "missingness_lower": value["detected"] / total, "missingness_upper": (value["detected"] + value["unknown"]) / total})
    return rows


def panel(axis: plt.Axes, rows: list[dict[str, object]], panel_name: str, ylabel: bool) -> None:
    lookup = {(row["panel"], row["rubric_type"], row["feedback_type"]): row for row in rows}
    if all(
        int(lookup[(panel_name, rubric, feedback)]["detected"])
        + int(lookup[(panel_name, rubric, feedback)]["not_detected"])
        == 0
        for rubric in RUBRICS
        for feedback in FEEDBACK
    ):
        axis.text(0.5, 0.5, "Unavailable\nprovider credits depleted", ha="center", va="center", transform=axis.transAxes, fontsize=12, color="#555555")
        axis.set_xticks([])
        axis.set_yticks([])
        axis.spines[["top", "right", "bottom", "left"]].set_visible(False)
        return
    width = 0.34
    centers = range(len(RUBRICS))
    for feedback, offset in zip(FEEDBACK, (-width / 2, width / 2), strict=True):
        selected = [lookup[(panel_name, rubric, feedback)] for rubric in RUBRICS]
        rates = [
            100 * float(
                row["missingness_lower"]
                if panel_name == "primary_any_detect"
                else row["detection_rate"] or 0.0
            )
            for row in selected
        ]
        positions = [center + offset for center in centers]
        bars = axis.bar(positions, rates, width, color=COLORS[feedback], label=FEEDBACK_LABELS[feedback], edgecolor="white")
        lowers = [100 * float(row["missingness_lower"]) for row in selected]
        uppers = [100 * float(row["missingness_upper"]) for row in selected]
        axis.vlines(positions, lowers, uppers, colors="#222222", linewidth=1.2, zorder=4)
        for bar, rate, row in zip(bars, rates, selected, strict=True):
            denominator = row["total"] if panel_name == "primary_any_detect" else int(row["detected"]) + int(row["not_detected"])
            axis.text(bar.get_x() + bar.get_width() / 2, rate + 0.6, f"{row['detected']}/{denominator}", ha="center", fontsize=8)
    maximum = max(100 * float(lookup[(panel_name, rubric, feedback)]["missingness_upper"]) for rubric in RUBRICS for feedback in FEEDBACK)
    axis.set_ylim(0, max(12, 5 * math.ceil((maximum + 6) / 5)))
    axis.set_xticks(list(centers), [RUBRIC_LABELS[item] for item in RUBRICS])
    if ylabel:
        axis.set_ylabel("Final-artifact direct RH detection rate (%)")
    axis.grid(axis="y", color="#D8D8D8")
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)


def write_outputs(path: Path, rows: list[dict[str, object]]) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with CSV_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("source_summary_sha256", *rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows({"source_summary_sha256": digest, **row} for row in rows)
    figure, axis = plt.subplots(figsize=(8.5, 6.0))
    panel(axis, rows, "available_any_detect", True)
    axis.set_title("Sealed final artifacts · available two-judge any-detect", fontweight="bold")
    figure.legend(*axis.get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(0.5, 0.92), ncol=2, frameon=False)
    figure.suptitle("BioMNIBench Results20: final-artifact direct RH", fontsize=15, fontweight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.86))
    figure.savefig(PRIMARY_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(PRIMARY_STEM.with_suffix(".pdf"), facecolor="white")
    figure, axes = plt.subplots(1, 3, figsize=(18, 6.0))
    for index, (axis, judge) in enumerate(zip(axes, JUDGES, strict=True)):
        panel(axis, rows, judge, index == 0)
        axis.set_title(JUDGE_LABELS[judge], fontweight="bold")
    figure.legend(*axes[0].get_legend_handles_labels(), loc="upper center", bbox_to_anchor=(0.5, 0.92), ncol=2, frameon=False)
    figure.suptitle("BioMNIBench Results20: final-artifact direct RH by judge", fontsize=15, fontweight="bold")
    figure.tight_layout(rect=(0, 0, 1, 0.86))
    figure.savefig(JUDGE_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(JUDGE_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    path, summary = load_summary()
    write_outputs(path, aggregate(summary))


if __name__ == "__main__":
    main()
