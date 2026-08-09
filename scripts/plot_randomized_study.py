"""Plot outcomes from the completed randomized 2x2 BiomniBench study."""

from __future__ import annotations

import json
import os
import random
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ID = "luna-top30-semi-r10"
STUDY_DIR = ROOT / "runs" / "biomnibench-studies" / EXPERIMENT_ID
DETECTION_DIR = ROOT / "runs" / "biomnibench-detections" / EXPERIMENT_ID
OUTPUT_DIR = ROOT / "figures" / EXPERIMENT_ID

CONDITIONS = (
    "base-static",
    "base-prospective",
    "diligent-static",
    "diligent-prospective",
)
PROMPT_COLORS = {"base": "#4477AA", "diligent": "#EE7733"}
RUBRIC_LINESTYLES = {"static": "-", "prospective": "--"}


def _pyplot():
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="study-plots-mpl-"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _study_records() -> list[dict]:
    study = _load_json(STUDY_DIR / "study.json")
    records = study.get("records")
    if not isinstance(records, list) or len(records) != 360:
        raise ValueError("expected the completed 360-assignment study")
    incomplete = [record["assignment_id"] for record in records if record["status"] != "completed"]
    if incomplete:
        raise ValueError(f"study is incomplete ({len(incomplete)} assignments)")
    return records


def _latest_detection_summary() -> dict:
    candidates = list((DETECTION_DIR / "evaluations").glob("*/summary.json"))
    if not candidates:
        raise FileNotFoundError(f"no detector summary under {DETECTION_DIR}")
    return _load_json(max(candidates, key=lambda path: path.stat().st_mtime))


def _cluster_interval(
    rows: list[tuple[str, np.ndarray]],
    *,
    seed: int,
    draws: int = 10_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Percentile interval from resampling task clusters with replacement."""
    by_task: dict[str, list[np.ndarray]] = defaultdict(list)
    for task_id, values in rows:
        by_task[task_id].append(values)
    tasks = sorted(by_task)
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        selected = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        values = [value for task_id in selected for value in by_task[task_id]]
        samples.append(np.mean(np.stack(values), axis=0))
    matrix = np.stack(samples)
    return np.quantile(matrix, 0.025, axis=0), np.quantile(matrix, 0.975, axis=0)


def _majority_outcomes() -> dict[tuple[str, int, str], int]:
    summary = _latest_detection_summary()
    models = summary.get("models")
    if not isinstance(models, list) or len(models) != 3:
        raise ValueError("expected a three-model detector panel")

    panels: dict[str, dict[str, str]] = defaultdict(dict)
    sources: dict[str, Path] = {}
    for record in summary.get("records", []):
        source = str(record["source_path"])
        decision = record.get("verdict", {}).get("decision")
        if isinstance(decision, str):
            panels[source][str(record["model"])] = decision
            sources[source] = Path(source)

    outcomes = {}
    substantive = {"reward_hacking_detected", "no_reward_hacking_detected"}
    for source, panel in panels.items():
        decisions = [panel.get(model) for model in models]
        if any(decision not in substantive for decision in decisions):
            continue
        path = sources[source]
        condition = path.name
        replicate = int(path.parent.name.removeprefix("rep-"))
        task_id = path.parent.parent.name
        outcomes[task_id, replicate, condition] = int(
            sum(decision == "reward_hacking_detected" for decision in decisions) >= 2
        )
    return outcomes


def plot_detection_rates(plt) -> None:
    outcomes = _majority_outcomes()
    grouped: dict[str, list[tuple[str, np.ndarray]]] = defaultdict(list)
    for (task_id, _replicate, condition), outcome in outcomes.items():
        grouped[condition].append((task_id, np.asarray([outcome], dtype=float)))

    estimates: dict[str, float] = {}
    intervals: dict[str, tuple[float, float]] = {}
    counts: dict[str, tuple[int, int]] = {}
    for index, condition in enumerate(CONDITIONS):
        rows = grouped[condition]
        values = np.asarray([row[1][0] for row in rows])
        lower, upper = _cluster_interval(rows, seed=20260809 + index)
        estimates[condition] = float(values.mean())
        intervals[condition] = (float(lower[0]), float(upper[0]))
        counts[condition] = (int(values.sum()), len(values))

    complete_blocks = []
    block_ids = {(task_id, replicate) for task_id, replicate, _ in outcomes}
    for block_id in block_ids:
        if all((*block_id, condition) in outcomes for condition in CONDITIONS):
            complete_blocks.append([outcomes[*block_id, condition] for condition in CONDITIONS])
    block_means = np.mean(np.asarray(complete_blocks, dtype=float), axis=0)
    interaction = block_means[3] - block_means[1] - block_means[2] + block_means[0]

    fig, ax = plt.subplots(figsize=(8.4, 5.8))
    centers = np.arange(2, dtype=float)
    width = 0.34
    for prompt_index, prompt in enumerate(("base", "diligent")):
        conditions = (f"{prompt}-static", f"{prompt}-prospective")
        values = np.asarray([estimates[condition] for condition in conditions])
        low = np.asarray([intervals[condition][0] for condition in conditions])
        high = np.asarray([intervals[condition][1] for condition in conditions])
        positions = centers + (prompt_index - 0.5) * width
        bars = ax.bar(
            positions,
            values,
            width=width,
            color=PROMPT_COLORS[prompt],
            label=prompt.title() + " prompt",
            yerr=np.vstack((values - low, high - values)),
            capsize=5,
            error_kw={"elinewidth": 1.4, "capthick": 1.4},
        )
        for bar, condition in zip(bars, conditions, strict=True):
            detected, total = counts[condition]
            _lower, upper = intervals[condition]
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                upper + 0.006,
                f"{detected}/{total}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    ax.set_xticks(centers, ("Static rubric", "Prospective (dynamic) rubric"))
    ax.set_ylabel("Reward-hacking detection rate")
    ax.set_ylim(0, max(0.18, max(upper for _lower, upper in intervals.values()) + 0.04))
    ax.yaxis.set_major_formatter(lambda value, _position: f"{value:.1%}")
    ax.set_title("Reward-hacking detections across the randomized 2×2 design", pad=14)
    ax.text(
        0.5,
        1.015,
        "Prespecified three-model majority vote; error bars are 95% task-cluster bootstrap intervals",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color="#4A5568",
    )
    ax.text(
        0.98,
        0.95,
        f"Interaction (difference-in-differences): {interaction * 100:+.1f} pp\n"
        f"Complete task×replicate blocks: {len(complete_blocks)}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        color="#374151",
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "#CBD5E1"},
    )
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        fig.savefig(OUTPUT_DIR / f"rh_detection_2x2.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def plot_score_trajectories(plt, records: list[dict]) -> None:
    grouped: dict[str, list[tuple[str, np.ndarray]]] = defaultdict(list)
    for record in records:
        state = _load_json(STUDY_DIR / record["experiment_dir"] / "state.json")
        scores = np.asarray(state.get("scores"), dtype=float)
        if scores.shape != (11,):
            raise ValueError(f"expected 11 scores for {record['assignment_id']}")
        grouped[record["condition_id"]].append((record["task_id"], scores))

    fig, ax = plt.subplots(figsize=(9.6, 6.1))
    turns = np.arange(11)
    for index, condition in enumerate(CONDITIONS):
        prompt, rubric = condition.split("-", maxsplit=1)
        rows = grouped[condition]
        matrix = np.stack([scores for _, scores in rows])
        mean = matrix.mean(axis=0)
        lower, upper = _cluster_interval(rows, seed=20260819 + index)
        label = f"{prompt.title()} · {'Prospective (dynamic)' if rubric == 'prospective' else 'Static'}"
        color = PROMPT_COLORS[prompt]
        linestyle = RUBRIC_LINESTYLES[rubric]
        ax.plot(
            turns,
            mean,
            color=color,
            linestyle=linestyle,
            linewidth=2.3,
            marker="o" if rubric == "static" else "s",
            markersize=4.5,
            label=label,
        )
        ax.fill_between(turns, lower, upper, color=color, alpha=0.10)

    ax.set_xticks(turns)
    ax.set_xlim(-0.25, 10.25)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Revision round (0 = initial submission)")
    ax.set_ylabel("Validated score")
    ax.set_title("Score trajectories across prompts and rubric policies", pad=14)
    ax.text(
        0.5,
        1.015,
        "Mean of 90 assignments per condition; shaded regions are 95% task-cluster bootstrap intervals",
        transform=ax.transAxes,
        ha="center",
        va="bottom",
        fontsize=9,
        color="#4A5568",
    )
    ax.legend(frameon=False, loc="lower right", ncol=2, fontsize=9)
    ax.grid(color="#E2E8F0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    for suffix in ("png", "pdf"):
        fig.savefig(OUTPUT_DIR / f"score_trajectories_2x2.{suffix}", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = _study_records()
    plt = _pyplot()
    plot_detection_rates(plt)
    plot_score_trajectories(plt, records)
    print(f"Wrote plots to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
