#!/usr/bin/env python3
"""Plot average original-rubric ensemble scores as bar charts."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from rubric_gen.biomnibench.visualization.backend import pyplot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "figures" / "luna-top30-original-rubric-ensemble-audit"
FEEDBACK = ("Semi", "Full")
CONDITIONS = (
    "base-static",
    "base-prospective",
    "diligent-static",
    "diligent-prospective",
)
CONDITION_LABELS = {
    "base-static": "Base\nStatic",
    "base-prospective": "Base\nDynamic",
    "diligent-static": "Diligent\nStatic",
    "diligent-prospective": "Diligent\nDynamic",
}
CONDITION_COLORS = {
    "base-static": "#4477AA",
    "base-prospective": "#66CCEE",
    "diligent-static": "#CC6677",
    "diligent-prospective": "#EE7733",
}


@dataclass(frozen=True)
class EnsembleRow:
    feedback: str
    assignment_id: str
    task_id: str
    replicate: int
    condition: str
    initial_score: float
    final_score: float
    score_delta: float


@dataclass(frozen=True)
class ConditionSummary:
    feedback: str
    condition: str
    assignments: int
    tasks: int
    initial_mean: float
    initial_ci_low: float
    initial_ci_high: float
    final_mean: float
    final_ci_low: float
    final_ci_high: float
    delta_mean: float
    delta_ci_low: float
    delta_ci_high: float
    final_score_100: int
    final_score_at_least_95: int


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_ensemble(path: Path, feedback: str) -> list[EnsembleRow]:
    summary = _load_json(path)
    totals = summary.get("totals")
    assignments = summary.get("assignments")
    protocol = summary.get("protocol")
    if (
        summary.get("schema_version") != 1
        or summary.get("kind") != "rubric-gen-planned-original-rubric-ensemble"
        or summary.get("status") != "completed"
        or type(totals) is not dict
        or totals.get("jobs") != 1_350
        or totals.get("completed") != 1_350
        or totals.get("failed") != 0
        or totals.get("pending") != 0
        or type(protocol) is not dict
        or protocol.get("rubric") != "original-human-written-r0000"
        or protocol.get("score_scale") != [0, 100]
        or type(assignments) is not dict
        or len(assignments) != 360
    ):
        raise ValueError(f"expected a completed original-rubric ensemble: {path}")

    rows = []
    for assignment_id, assignment in sorted(assignments.items()):
        if type(assignment_id) is not str or type(assignment) is not dict:
            raise ValueError("ensemble assignment identity is invalid")
        condition = assignment.get("condition_id")
        ensemble = assignment.get("ensemble")
        judges = assignment.get("judges")
        if (
            condition not in CONDITIONS
            or type(ensemble) is not dict
            or ensemble.get("status") != "completed"
            or type(judges) is not dict
            or len(judges) != 3
        ):
            raise ValueError(f"invalid ensemble assignment: {assignment_id}")
        initial = float(ensemble["initial_mean"])
        final = float(ensemble["final_mean"])
        delta = float(ensemble["mean_delta"])
        if (
            not 0 <= initial <= 100
            or not 0 <= final <= 100
            or abs(delta - (final - initial)) > 1e-9
            or abs(
                initial
                - fmean(float(judge["initial_score"]) for judge in judges.values())
            ) > 1e-9
            or abs(
                final
                - fmean(float(judge["final_score"]) for judge in judges.values())
            ) > 1e-9
        ):
            raise ValueError(f"ensemble score changed: {assignment_id}")
        rows.append(EnsembleRow(
            feedback=feedback,
            assignment_id=assignment_id,
            task_id=str(assignment["task_id"]),
            replicate=int(assignment["replicate"]),
            condition=str(condition),
            initial_score=initial,
            final_score=final,
            score_delta=delta,
        ))

    keys = {(row.task_id, row.replicate, row.condition) for row in rows}
    counts = {
        condition: sum(row.condition == condition for row in rows)
        for condition in CONDITIONS
    }
    if len(rows) != 360 or len(keys) != 360:
        raise ValueError(f"expected 360 unique assignments: {path}")
    if counts != {condition: 90 for condition in CONDITIONS}:
        raise ValueError(f"expected 90 assignments per condition: {path}")
    return rows


def _cluster_interval(
    rows: list[EnsembleRow],
    field: str,
    *,
    draws: int,
    seed: int,
) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[row.task_id].append(float(getattr(row, field)))
    tasks = sorted(by_task)
    if len(tasks) != 30 or any(len(by_task[task]) != 3 for task in tasks):
        raise ValueError("each condition must contain 30 tasks and 3 replicates")
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        selected = [tasks[rng.randrange(len(tasks))] for _task in tasks]
        estimates.append(fmean(
            value
            for task in selected
            for value in by_task[task]
        ))
    estimates.sort()
    return (
        estimates[int(0.025 * (draws - 1))],
        estimates[int(0.975 * (draws - 1))],
    )


def summarize(
    rows: list[EnsembleRow],
    *,
    draws: int,
) -> list[ConditionSummary]:
    grouped: dict[tuple[str, str], list[EnsembleRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.feedback, row.condition)].append(row)
    output = []
    for feedback_index, feedback in enumerate(FEEDBACK):
        for condition_index, condition in enumerate(CONDITIONS):
            group = grouped[(feedback, condition)]
            if len(group) != 90:
                raise ValueError(f"expected 90 assignments: {feedback} {condition}")
            seed = 20260811 + feedback_index * 100 + condition_index * 10
            initial_low, initial_high = _cluster_interval(
                group,
                "initial_score",
                draws=draws,
                seed=seed,
            )
            final_low, final_high = _cluster_interval(
                group,
                "final_score",
                draws=draws,
                seed=seed + 1,
            )
            delta_low, delta_high = _cluster_interval(
                group,
                "score_delta",
                draws=draws,
                seed=seed + 2,
            )
            output.append(ConditionSummary(
                feedback=feedback,
                condition=condition,
                assignments=len(group),
                tasks=len({row.task_id for row in group}),
                initial_mean=fmean(row.initial_score for row in group),
                initial_ci_low=initial_low,
                initial_ci_high=initial_high,
                final_mean=fmean(row.final_score for row in group),
                final_ci_low=final_low,
                final_ci_high=final_high,
                delta_mean=fmean(row.score_delta for row in group),
                delta_ci_low=delta_low,
                delta_ci_high=delta_high,
                final_score_100=sum(row.final_score == 100 for row in group),
                final_score_at_least_95=sum(row.final_score >= 95 for row in group),
            ))
    return output


def _lookup(
    summaries: list[ConditionSummary],
) -> dict[tuple[str, str], ConditionSummary]:
    return {(row.feedback, row.condition): row for row in summaries}


def plot_average_scores(
    summaries: list[ConditionSummary],
    output: Path,
) -> None:
    plt = pyplot()
    lookup = _lookup(summaries)
    figure, axes = plt.subplots(1, 2, figsize=(14, 6.8), sharey=True)
    width = 0.36
    positions = list(range(len(CONDITIONS)))
    for axis, feedback in zip(axes, FEEDBACK, strict=True):
        values = [lookup[(feedback, condition)] for condition in CONDITIONS]
        initial_means = [row.initial_mean for row in values]
        final_means = [row.final_mean for row in values]
        initial_errors = [
            [row.initial_mean - row.initial_ci_low for row in values],
            [row.initial_ci_high - row.initial_mean for row in values],
        ]
        final_errors = [
            [row.final_mean - row.final_ci_low for row in values],
            [row.final_ci_high - row.final_mean for row in values],
        ]
        initial_bars = axis.bar(
            [position - width / 2 for position in positions],
            initial_means,
            width,
            yerr=initial_errors,
            capsize=3,
            color="#BBBBBB",
            edgecolor="white",
            label="Initial s000",
        )
        final_bars = axis.bar(
            [position + width / 2 for position in positions],
            final_means,
            width,
            yerr=final_errors,
            capsize=3,
            color=[CONDITION_COLORS[condition] for condition in CONDITIONS],
            edgecolor="white",
            label="Final s010",
        )
        axis.bar_label(initial_bars, fmt="%.1f", padding=3, fontsize=9)
        axis.bar_label(final_bars, fmt="%.1f", padding=3, fontsize=9)
        axis.set_xticks(positions)
        axis.set_xticklabels([CONDITION_LABELS[value] for value in CONDITIONS])
        axis.set_ylim(0, 110)
        axis.set_title(f"{feedback} feedback", fontsize=13, weight="bold")
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.7)
        axis.set_axisbelow(True)
    axes[0].set_ylabel("Average original-rubric ensemble score (0–100)")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        ncol=2,
        frameon=False,
        bbox_to_anchor=(0.5, 0.865),
    )
    figure.suptitle(
        "Average original-rubric ensemble scores by condition\n"
        "Error bars are 95% task-cluster bootstrap intervals",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.80))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"average_ensemble_scores.{suffix}", dpi=220)
    plt.close(figure)


def plot_average_changes(
    summaries: list[ConditionSummary],
    output: Path,
) -> None:
    plt = pyplot()
    lookup = _lookup(summaries)
    figure, axes = plt.subplots(1, 2, figsize=(14, 6.8), sharey=True)
    positions = list(range(len(CONDITIONS)))
    for axis, feedback in zip(axes, FEEDBACK, strict=True):
        values = [lookup[(feedback, condition)] for condition in CONDITIONS]
        means = [row.delta_mean for row in values]
        errors = [
            [row.delta_mean - row.delta_ci_low for row in values],
            [row.delta_ci_high - row.delta_mean for row in values],
        ]
        bars = axis.bar(
            positions,
            means,
            yerr=errors,
            capsize=3,
            color=[CONDITION_COLORS[condition] for condition in CONDITIONS],
            edgecolor="white",
        )
        axis.bar_label(bars, fmt="%+.1f", padding=3, fontsize=10)
        axis.axhline(0, color="#555555", linewidth=1)
        axis.set_xticks(positions)
        axis.set_xticklabels([CONDITION_LABELS[value] for value in CONDITIONS])
        axis.set_ylim(0, 95)
        axis.set_title(f"{feedback} feedback", fontsize=13, weight="bold")
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.7)
        axis.set_axisbelow(True)
    axes[0].set_ylabel("Average final − initial ensemble score")
    figure.suptitle(
        "Average original-rubric ensemble score change\n"
        "Error bars are 95% task-cluster bootstrap intervals",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.9))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"average_ensemble_score_changes.{suffix}", dpi=220)
    plt.close(figure)


def write_summary(summaries: list[ConditionSummary], output: Path) -> None:
    fields = tuple(ConditionSummary.__dataclass_fields__)
    with (output / "ensemble_score_summary.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in summaries:
            writer.writerow({field: getattr(row, field) for field in fields})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    judgments = ROOT / "runs" / "biomnibench-judgments"
    parser.add_argument(
        "--semi-ensemble",
        type=Path,
        default=(
            judgments
            / "luna-top30-semi-r10-original-rubric-deduplicated/summary.json"
        ),
    )
    parser.add_argument(
        "--full-ensemble",
        type=Path,
        default=(
            judgments
            / "luna-top30-full-r10-original-rubric-deduplicated/summary.json"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.bootstrap_draws < 1_000:
        raise ValueError("bootstrap-draws must be at least 1,000")
    rows = [
        *load_ensemble(args.semi_ensemble, "Semi"),
        *load_ensemble(args.full_ensemble, "Full"),
    ]
    summaries = summarize(rows, draws=args.bootstrap_draws)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_summary(summaries, args.output_dir)
    plot_average_scores(summaries, args.output_dir)
    plot_average_changes(summaries, args.output_dir)
    print(f"wrote ensemble bar plots to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
