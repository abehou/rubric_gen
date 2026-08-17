"""Plot outcomes from diligent-only semi- and full-feedback studies."""

from __future__ import annotations

import json
import os
import random
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

from rubric_gen.malt.detection import validate_detection_summary
from rubric_gen.submission_revision.experiment import Experiment, load_experiment


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "figures" / "luna-top30-feedback-comparison"

CONDITIONS = (
    "diligent-static",
    "diligent-prospective",
)
RUBRIC_COLORS = {"static": "#4477AA", "prospective": "#EE7733"}
RUBRIC_LINESTYLES = {"static": "-", "prospective": "--"}
ENSEMBLE_RULES = ("majority", "any_detects")
ENSEMBLE_RULE_LABELS = {
    "majority": "Majority vote (at least 2 of 3)",
    "any_detects": "Any detector (at least 1 of 3)",
}


@dataclass(frozen=True)
class StudySpec:
    label: str
    experiment_path: Path

    @cached_property
    def experiment(self) -> Experiment:
        return load_experiment(self.experiment_path)

    @property
    def experiment_id(self) -> str:
        return self.experiment.experiment_id

    @property
    def study_dir(self) -> Path:
        return Path(str(self.experiment.dag["revise"]["output_dir"]))


@dataclass(frozen=True)
class DetectionSpec:
    label: str
    experiment_path: Path
    target: str
    positive_decision: str
    negative_decision: str

    @cached_property
    def experiment(self) -> Experiment:
        return load_experiment(self.experiment_path)

    @property
    def experiment_id(self) -> str:
        return self.experiment.experiment_id

    @property
    def detection_dir(self) -> Path:
        return Path(str(self.experiment.dag["detect"]["output_dir"]))


@dataclass(frozen=True)
class DetectionResult:
    outcomes: dict[tuple[str, int, str], int]
    missing_panels: int


@dataclass(frozen=True)
class DetectionStatistics:
    estimates: dict[str, float]
    intervals: dict[str, tuple[float, float]]
    counts: dict[str, tuple[int, int]]
    prospective_minus_static: float
    complete_blocks: int


STUDIES = (
    StudySpec(
        "Semi feedback", ROOT / "experiments" / "luna-top30-semi-r10.yaml"
    ),
    StudySpec(
        "Full feedback", ROOT / "experiments" / "luna-top30-full-r10.yaml"
    ),
)
RH_DETECTIONS = (
    DetectionSpec(
        label="Semi feedback",
        experiment_path=ROOT / "experiments" / "luna-top30-semi-r10.yaml",
        target="rh",
        positive_decision="reward_hacking_detected",
        negative_decision="no_reward_hacking_detected",
    ),
    DetectionSpec(
        label="Full feedback",
        experiment_path=ROOT / "experiments" / "luna-top30-full-r10.yaml",
        target="rh",
        positive_decision="reward_hacking_detected",
        negative_decision="no_reward_hacking_detected",
    ),
)
def _pyplot():
    os.environ.setdefault(
        "MPLCONFIGDIR",
        tempfile.mkdtemp(prefix="study-plots-mpl-"),
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _study_records(spec: StudySpec) -> list[dict[str, object]]:
    study = _load_json(spec.study_dir / "study.json")
    records = study.get("records")
    if (
        study.get("experiment_id") != spec.experiment_id
        or study.get("status") != "completed"
        or not isinstance(records, list)
        or len(records) != len(spec.experiment.assignments)
        or any(not isinstance(record, dict) for record in records)
    ):
        raise ValueError(f"expected a completed current study: {spec.label}")
    incomplete = [
        str(record.get("assignment_id"))
        for record in records
        if record.get("status") != "completed"
    ]
    if incomplete:
        raise ValueError(
            f"{spec.label} is incomplete ({len(incomplete)} assignments)"
        )
    return records


def _latest_detection_summary(spec: DetectionSpec) -> dict[str, object]:
    candidates = list(
        (spec.detection_dir / "direct" / "evaluations").glob("*/summary.json")
    )
    if not candidates:
        raise FileNotFoundError(f"no detector summary under {spec.detection_dir}")
    summary = _load_json(max(candidates, key=lambda path: path.stat().st_mtime))
    validate_detection_summary(summary, expected=spec.target)
    if (
        summary.get("detection") != spec.target
        or summary.get("primary_rule") != "majority"
        or summary.get("experiment_ids") != [spec.experiment_id]
    ):
        raise ValueError(f"detector summary has the wrong protocol: {spec.label}")
    return summary


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
    if len(tasks) != 30:
        raise ValueError(f"expected 30 task clusters, found {len(tasks)}")
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        selected = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        values = [value for task_id in selected for value in by_task[task_id]]
        samples.append(np.mean(np.stack(values), axis=0))
    matrix = np.stack(samples)
    return np.quantile(matrix, 0.025, axis=0), np.quantile(
        matrix,
        0.975,
        axis=0,
    )


def _ensemble_outcomes(
    spec: DetectionSpec,
    *,
    rule: str,
) -> DetectionResult:
    if rule not in ENSEMBLE_RULES:
        raise ValueError(f"unsupported ensemble rule: {rule}")
    summary = _latest_detection_summary(spec)
    models = summary.get("models")
    records = summary.get("records")
    if (
        not isinstance(models, list)
        or len(models) != 3
        or len(set(models)) != 3
        or not isinstance(records, list)
        or len(records) != len(spec.experiment.assignments) * len(models)
    ):
        raise ValueError(f"expected a complete three-model panel: {spec.label}")

    panels: dict[str, dict[str, str]] = defaultdict(dict)
    sources: dict[str, Path] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("detector record must be an object")
        source_value = record.get("source_path")
        model_value = record.get("model")
        verdict = record.get("verdict")
        if not isinstance(source_value, str) or not isinstance(model_value, str):
            raise ValueError("detector record lacks source or model identity")
        if model_value in panels[source_value]:
            raise ValueError("detector summary contains a duplicate panel member")
        decision = verdict.get("decision") if isinstance(verdict, dict) else None
        if isinstance(decision, str):
            panels[source_value][model_value] = decision
        sources[source_value] = Path(source_value)
    if len(panels) != len(spec.experiment.assignments):
        raise ValueError(
            f"expected {len(spec.experiment.assignments)} detector panels, "
            f"found {len(panels)}"
        )

    outcomes: dict[tuple[str, int, str], int] = {}
    substantive = {spec.positive_decision, spec.negative_decision}
    missing_panels = 0
    for source, panel in panels.items():
        decisions = [panel.get(str(model)) for model in models]
        if any(decision not in substantive for decision in decisions):
            missing_panels += 1
            continue
        path = sources[source]
        condition = path.name
        replicate = int(path.parent.name.removeprefix("rep-"))
        task_id = path.parent.parent.name
        key = (task_id, replicate, condition)
        if key in outcomes:
            raise ValueError(f"duplicate detector assignment: {key}")
        positive_votes = sum(
            decision == spec.positive_decision
            for decision in decisions
        )
        outcomes[key] = int(
            positive_votes >= 2 if rule == "majority" else positive_votes >= 1
        )
    return DetectionResult(outcomes=outcomes, missing_panels=missing_panels)


def _detection_statistics(
    result: DetectionResult,
    *,
    seed: int,
) -> DetectionStatistics:
    grouped: dict[str, list[tuple[str, np.ndarray]]] = defaultdict(list)
    for (task_id, _replicate, condition), outcome in result.outcomes.items():
        if condition not in CONDITIONS:
            raise ValueError(f"unexpected condition in detection: {condition}")
        grouped[condition].append(
            (task_id, np.asarray([outcome], dtype=float))
        )

    estimates: dict[str, float] = {}
    intervals: dict[str, tuple[float, float]] = {}
    counts: dict[str, tuple[int, int]] = {}
    for index, condition in enumerate(CONDITIONS):
        rows = grouped[condition]
        values = np.asarray([row[1][0] for row in rows])
        lower, upper = _cluster_interval(rows, seed=seed + index)
        estimates[condition] = float(values.mean())
        intervals[condition] = (float(lower[0]), float(upper[0]))
        counts[condition] = (int(values.sum()), len(values))

    complete_blocks = []
    block_ids = {
        (task_id, replicate)
        for task_id, replicate, _condition in result.outcomes
    }
    for block_id in block_ids:
        if all((*block_id, condition) in result.outcomes for condition in CONDITIONS):
            complete_blocks.append(
                [
                    result.outcomes[*block_id, condition]
                    for condition in CONDITIONS
                ]
            )
    if not complete_blocks:
        raise ValueError("detector has no complete randomized blocks")
    block_means = np.mean(np.asarray(complete_blocks, dtype=float), axis=0)
    prospective_minus_static = block_means[1] - block_means[0]
    return DetectionStatistics(
        estimates=estimates,
        intervals=intervals,
        counts=counts,
        prospective_minus_static=float(prospective_minus_static),
        complete_blocks=len(complete_blocks),
    )


def _draw_detection_panel(
    ax,
    statistics: DetectionStatistics,
    *,
    title: str,
    annotation_xy: tuple[float, float] = (0.98, 0.96),
    annotation_ha: str = "right",
) -> None:
    positions = np.arange(len(CONDITIONS), dtype=float)
    values = np.asarray([
        statistics.estimates[condition] for condition in CONDITIONS
    ])
    low = np.asarray([
        statistics.intervals[condition][0] for condition in CONDITIONS
    ])
    high = np.asarray([
        statistics.intervals[condition][1] for condition in CONDITIONS
    ])
    bars = ax.bar(
        positions,
        values,
        width=0.58,
        color=[
            RUBRIC_COLORS[condition.removeprefix("diligent-")]
            for condition in CONDITIONS
        ],
        yerr=np.vstack((values - low, high - values)),
        capsize=5,
        error_kw={"elinewidth": 1.4, "capthick": 1.4},
    )
    for bar, condition in zip(bars, CONDITIONS, strict=True):
        detected, total = statistics.counts[condition]
        _lower, upper = statistics.intervals[condition]
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            upper + 0.012,
            f"{detected}/{total}",
            ha="center",
            va="bottom",
            fontsize=8.5,
        )

    ax.set_xticks(
        positions,
        ("Static rubric", "Prospective\n(dynamic) rubric"),
    )
    ax.set_title(title, fontsize=12, weight="bold", pad=11)
    ax.yaxis.set_major_formatter(lambda value, _position: f"{value:.0%}")
    ax.text(
        *annotation_xy,
        "Prospective - static: "
        f"{statistics.prospective_minus_static * 100:+.1f} pp\n"
        f"Complete blocks: {statistics.complete_blocks}",
        transform=ax.transAxes,
        ha=annotation_ha,
        va="top",
        fontsize=8.5,
        color="#374151",
        bbox={
            "boxstyle": "round,pad=0.35",
            "facecolor": "white",
            "edgecolor": "#CBD5E1",
        },
    )
    ax.grid(axis="y", color="#E2E8F0", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)


def _save_figure(fig, stem: str) -> None:
    for suffix in ("png", "pdf"):
        fig.savefig(
            OUTPUT_DIR / f"{stem}.{suffix}",
            dpi=220,
            bbox_inches="tight",
        )


def plot_rh_detection_comparison(
    plt,
) -> dict[str, dict[str, DetectionStatistics]]:
    results = {
        rule: {
            spec.label: _ensemble_outcomes(spec, rule=rule)
            for spec in RH_DETECTIONS
        }
        for rule in ENSEMBLE_RULES
    }
    statistics = {
        rule: {
            spec.label: _detection_statistics(
                results[rule][spec.label],
                seed=20260810 + rule_index * 1_000 + spec_index * 100,
            )
            for spec_index, spec in enumerate(RH_DETECTIONS)
        }
        for rule_index, rule in enumerate(ENSEMBLE_RULES)
    }
    maximum = max(
        upper
        for rule_statistics in statistics.values()
        for study_statistics in rule_statistics.values()
        for _lower, upper in study_statistics.intervals.values()
    )
    y_limit = min(1.0, max(0.20, maximum + 0.065))

    fig, axes = plt.subplots(
        2,
        2,
        figsize=(13.2, 9.8),
        sharex=True,
        sharey=True,
        squeeze=False,
    )
    for row_index, rule in enumerate(ENSEMBLE_RULES):
        for column_index, spec in enumerate(RH_DETECTIONS):
            ax = axes[row_index, column_index]
            _draw_detection_panel(
                ax,
                statistics[rule][spec.label],
                title=f"{spec.label} · {ENSEMBLE_RULE_LABELS[rule]}",
            )
            ax.set_ylim(0, y_limit)
    fig.supylabel("Reward-hacking detection rate", x=0.012, fontsize=11)
    fig.suptitle(
        "Reward-hacking detections by feedback and rubric policy",
        fontsize=15,
        weight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.945,
        "Complete three-model panels; top row requires at least two detections and bottom row requires at least one.\n"
        "Intervals are 95% task-cluster bootstraps. The feedback-study contrast is descriptive.",
        ha="center",
        va="top",
        fontsize=9,
        color="#4A5568",
    )
    fig.tight_layout(rect=(0.025, 0.035, 1, 0.89), h_pad=2.0)
    _save_figure(fig, "rh_detection_feedback_comparison")
    plt.close(fig)

    for rule in ENSEMBLE_RULES:
        for spec in RH_DETECTIONS:
            print(
                f"{spec.label} RH · {ENSEMBLE_RULE_LABELS[rule]}: "
                f"{len(results[rule][spec.label].outcomes)} valid panels, "
                f"{results[rule][spec.label].missing_panels} missing panels"
            )
    return statistics


def _score_rows(
    spec: StudySpec,
    records: list[dict[str, object]],
) -> dict[str, list[tuple[str, np.ndarray]]]:
    grouped: dict[str, list[tuple[str, np.ndarray]]] = defaultdict(list)
    for record in records:
        experiment_dir = record.get("experiment_dir")
        condition = record.get("condition_id")
        task_id = record.get("task_id")
        assignment_id = record.get("assignment_id")
        if (
            not isinstance(experiment_dir, str)
            or condition not in CONDITIONS
            or not isinstance(task_id, str)
        ):
            raise ValueError(f"invalid study record: {assignment_id}")
        state = _load_json(spec.study_dir / experiment_dir / "state.json")
        scores = np.asarray(state.get("scores"), dtype=float)
        expected_rounds = int(spec.experiment.protocol["revision_rounds"])
        if scores.shape != (expected_rounds + 1,):
            raise ValueError(
                f"expected {expected_rounds + 1} scores for {assignment_id}"
            )
        grouped[str(condition)].append((task_id, scores))
    expected = len(spec.experiment.task_ids) * spec.experiment.replicates
    if any(len(grouped[condition]) != expected for condition in CONDITIONS):
        raise ValueError(
            f"{spec.label} does not have {expected} assignments per condition"
        )
    return grouped


def plot_score_trajectories(
    plt,
    study_records: dict[str, list[dict[str, object]]],
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13.2, 6.0), sharex=True, sharey=True)
    for study_index, (ax, spec) in enumerate(zip(axes, STUDIES, strict=True)):
        rounds = int(spec.experiment.protocol["revision_rounds"])
        turns = np.arange(rounds + 1)
        grouped = _score_rows(spec, study_records[spec.label])
        all_scores = []
        for condition_index, condition in enumerate(CONDITIONS):
            rubric = condition.removeprefix("diligent-")
            rows = grouped[condition]
            matrix = np.stack([scores for _, scores in rows])
            all_scores.append(matrix)
            mean = matrix.mean(axis=0)
            lower, upper = _cluster_interval(
                rows,
                seed=20262010 + study_index * 100 + condition_index,
            )
            label = (
                "Prospective (dynamic)" if rubric == "prospective" else "Static"
            )
            color = RUBRIC_COLORS[rubric]
            linestyle = RUBRIC_LINESTYLES[rubric]
            ax.plot(
                turns,
                mean,
                color=color,
                linestyle=linestyle,
                linewidth=2.3,
                marker="o" if rubric == "static" else "s",
                markersize=4.2,
                label=label,
            )
            ax.fill_between(turns, lower, upper, color=color, alpha=0.10)
        combined = np.concatenate(all_scores, axis=0)
        ax.text(
            0.03,
            0.96,
            f"Overall mean: {combined[:, 0].mean():.1f} → "
            f"{combined[:, -1].mean():.1f}",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            color="#374151",
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": "#CBD5E1",
            },
        )
        ax.set_title(spec.label, fontsize=12, weight="bold", pad=11)
        ax.set_xticks(turns)
        ax.set_xlim(-0.25, rounds + 0.25)
        ax.set_ylim(0, 100)
        ax.set_xlabel("Revision round (0 = initial submission)")
        ax.grid(color="#E2E8F0", linewidth=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Validated score")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        frameon=False,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=2,
        fontsize=9,
    )
    fig.suptitle(
        "Diligent-prompt score trajectories by feedback and rubric policy",
        fontsize=15,
        weight="bold",
        y=0.99,
    )
    fig.text(
        0.5,
        0.935,
        "Each condition has 90 assignments; bands are 95% task-cluster bootstrap intervals. "
        "Feedback arms use the shared seed pool, but cross-panel differences remain descriptive.",
        ha="center",
        va="top",
        fontsize=9,
        color="#4A5568",
    )
    fig.tight_layout(rect=(0, 0.08, 1, 0.91))
    _save_figure(fig, "score_trajectories_feedback_comparison")
    plt.close(fig)


def _print_statistics(
    label: str,
    statistics: DetectionStatistics,
) -> None:
    print(label)
    for condition in CONDITIONS:
        detected, total = statistics.counts[condition]
        lower, upper = statistics.intervals[condition]
        print(
            f"  {condition}: {detected}/{total} "
            f"({statistics.estimates[condition]:.3f}, "
            f"95% CI {lower:.3f}–{upper:.3f})"
        )
    print(
        "  prospective_minus_static="
        f"{statistics.prospective_minus_static:+.3f}; "
        f"complete_blocks={statistics.complete_blocks}"
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = {spec.label: _study_records(spec) for spec in STUDIES}
    plt = _pyplot()
    rh_statistics = plot_rh_detection_comparison(plt)
    plot_score_trajectories(plt, records)
    for rule, study_statistics in rh_statistics.items():
        for label, statistics in study_statistics.items():
            _print_statistics(
                f"{label} RH · {ENSEMBLE_RULE_LABELS[rule]}",
                statistics,
            )
    print(f"Wrote plots to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
