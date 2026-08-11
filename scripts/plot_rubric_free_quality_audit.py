#!/usr/bin/env python3
"""Plot the completed rubric-free pairwise quality audit by study condition."""

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
DEFAULT_OUTPUT = ROOT / "figures" / "luna-top30-rubric-free-quality-audit"
DIMENSIONS = (
    "completeness",
    "factual_correctness",
    "conciseness",
    "relevance",
    "safety",
    "overall",
)
DIMENSION_LABELS = {
    "completeness": "Completeness",
    "factual_correctness": "Factual correctness",
    "conciseness": "Conciseness",
    "relevance": "Relevance",
    "safety": "Safety",
    "overall": "Overall quality",
}
CONDITIONS = (
    "base-static",
    "base-prospective",
    "diligent-static",
    "diligent-prospective",
)
CONDITION_LABELS = {
    "base-static": "Base · Static",
    "base-prospective": "Base · Dynamic",
    "diligent-static": "Diligent · Static",
    "diligent-prospective": "Diligent · Dynamic",
}
FEEDBACK = ("Semi", "Full")
COLORS = {
    "base-static": "#4477AA",
    "base-prospective": "#66CCEE",
    "diligent-static": "#CC6677",
    "diligent-prospective": "#EE7733",
}


@dataclass(frozen=True)
class AuditRow:
    feedback: str
    assignment_id: str
    task_id: str
    replicate: int
    condition: str
    initial: dict[str, float]
    final: dict[str, float]
    delta: dict[str, float]
    majority_winner: str
    consensus_winner: str | None


@dataclass(frozen=True)
class MetricSummary:
    feedback: str
    condition: str
    dimension: str
    assignments: int
    tasks: int
    initial_mean: float
    final_mean: float
    delta_mean: float
    delta_ci_low: float
    delta_ci_high: float
    majority_eligible: int
    majority_final_wins: int
    majority_final_win_rate: float
    consensus_eligible: int
    consensus_final_wins: int
    consensus_final_win_rate: float | None


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"expected JSON object: {path}")
    return value


def _score_map(value: object, label: str) -> dict[str, float]:
    if type(value) is not dict or set(value) != set(DIMENSIONS):
        raise ValueError(f"{label} has invalid quality dimensions")
    output: dict[str, float] = {}
    for dimension in DIMENSIONS:
        score = value[dimension]
        if type(score) not in {int, float} or not 1 <= float(score) <= 7:
            raise ValueError(f"{label} has an invalid {dimension} score")
        output[dimension] = float(score)
    return output


def load_audit(path: Path, feedback: str) -> list[AuditRow]:
    summary = _load_json(path)
    assignments = summary.get("assignments")
    totals = summary.get("totals")
    if (
        summary.get("schema_version") != 1
        or summary.get("kind") != "rubric-free-pairwise-final-evaluation"
        or summary.get("status") != "completed"
        or type(totals) is not dict
        or totals.get("jobs") != 2_160
        or totals.get("completed") != 2_160
        or totals.get("failed") != 0
        or totals.get("pending") != 0
        or type(assignments) is not dict
        or len(assignments) != 360
    ):
        raise ValueError(f"expected a completed 360-pair audit: {path}")
    rows: list[AuditRow] = []
    for assignment_id, assignment in sorted(assignments.items()):
        if type(assignment_id) is not str or type(assignment) is not dict:
            raise ValueError("pairwise assignment identity is invalid")
        condition = assignment.get("condition_id")
        panel = assignment.get("panel")
        if (
            condition not in CONDITIONS
            or type(panel) is not dict
            or panel.get("status") != "completed"
            or panel.get("majority_winner") not in {"initial", "final", "tie"}
            or panel.get("consensus_winner") not in {"initial", "final", None}
            or assignment.get("submission_ids") != ["s000", "s010"]
        ):
            raise ValueError(f"invalid completed panel: {assignment_id}")
        initial = _score_map(
            panel.get("initial_mean_scores"),
            f"{assignment_id} initial",
        )
        final = _score_map(
            panel.get("final_mean_scores"),
            f"{assignment_id} final",
        )
        delta = panel.get("mean_score_deltas")
        if type(delta) is not dict or set(delta) != set(DIMENSIONS):
            raise ValueError(f"invalid score deltas: {assignment_id}")
        deltas = {dimension: float(delta[dimension]) for dimension in DIMENSIONS}
        if any(
            abs(deltas[dimension] - (final[dimension] - initial[dimension]))
            > 1e-9
            for dimension in DIMENSIONS
        ):
            raise ValueError(f"score delta changed: {assignment_id}")
        rows.append(AuditRow(
            feedback=feedback,
            assignment_id=assignment_id,
            task_id=str(assignment["task_id"]),
            replicate=int(assignment["replicate"]),
            condition=str(condition),
            initial=initial,
            final=final,
            delta=deltas,
            majority_winner=str(panel["majority_winner"]),
            consensus_winner=panel["consensus_winner"],
        ))
    keys = {(row.task_id, row.replicate, row.condition) for row in rows}
    if len(keys) != 360:
        raise ValueError(f"pairwise audit contains duplicate assignments: {path}")
    return rows


def _task_cluster_interval(
    rows: list[AuditRow],
    dimension: str,
    *,
    draws: int,
    seed: int,
) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[row.task_id].append(row.delta[dimension])
    tasks = sorted(by_task)
    if len(tasks) != 30 or any(len(by_task[task]) != 3 for task in tasks):
        raise ValueError("each condition must contain 30 tasks and 3 replicates")
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sample = [tasks[rng.randrange(len(tasks))] for _task in tasks]
        estimates.append(fmean(
            value
            for task in sample
            for value in by_task[task]
        ))
    estimates.sort()
    return (
        estimates[int(0.025 * (draws - 1))],
        estimates[int(0.975 * (draws - 1))],
    )


def summarize(
    rows: list[AuditRow],
    *,
    draws: int,
) -> list[MetricSummary]:
    grouped: dict[tuple[str, str], list[AuditRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.feedback, row.condition)].append(row)
    if set(grouped) != {
        (feedback, condition)
        for feedback in FEEDBACK
        for condition in CONDITIONS
    }:
        raise ValueError("quality audit does not contain all eight conditions")
    output = []
    for group_index, ((feedback, condition), group) in enumerate(sorted(grouped.items())):
        if len(group) != 90:
            raise ValueError(f"expected 90 assignments: {feedback} {condition}")
        majority = [row for row in group if row.majority_winner != "tie"]
        consensus = [
            row for row in group
            if row.consensus_winner in {"initial", "final"}
        ]
        for dimension_index, dimension in enumerate(DIMENSIONS):
            low, high = _task_cluster_interval(
                group,
                dimension,
                draws=draws,
                seed=20260810 + group_index * 100 + dimension_index,
            )
            consensus_wins = sum(
                row.consensus_winner == "final" for row in consensus
            )
            output.append(MetricSummary(
                feedback=feedback,
                condition=condition,
                dimension=dimension,
                assignments=len(group),
                tasks=len({row.task_id for row in group}),
                initial_mean=fmean(row.initial[dimension] for row in group),
                final_mean=fmean(row.final[dimension] for row in group),
                delta_mean=fmean(row.delta[dimension] for row in group),
                delta_ci_low=low,
                delta_ci_high=high,
                majority_eligible=len(majority),
                majority_final_wins=sum(
                    row.majority_winner == "final" for row in majority
                ),
                majority_final_win_rate=fmean(
                    row.majority_winner == "final" for row in majority
                ),
                consensus_eligible=len(consensus),
                consensus_final_wins=consensus_wins,
                consensus_final_win_rate=(
                    consensus_wins / len(consensus) if consensus else None
                ),
            ))
    return output


def _group_order() -> list[tuple[str, str]]:
    return [
        (feedback, condition)
        for feedback in FEEDBACK
        for condition in CONDITIONS
    ]


def _group_label(feedback: str, condition: str) -> str:
    return f"{feedback} · {CONDITION_LABELS[condition]}"


def plot_delta_intervals(
    summaries: list[MetricSummary],
    output: Path,
) -> None:
    plt = pyplot()
    lookup = {
        (row.feedback, row.condition, row.dimension): row
        for row in summaries
    }
    groups = _group_order()
    figure, axes = plt.subplots(2, 3, figsize=(15, 9.5), sharex=True, sharey=True)
    for axis, dimension in zip(axes.flat, DIMENSIONS, strict=True):
        for y, (feedback, condition) in enumerate(groups):
            row = lookup[(feedback, condition, dimension)]
            axis.errorbar(
                row.delta_mean,
                y,
                xerr=[
                    [row.delta_mean - row.delta_ci_low],
                    [row.delta_ci_high - row.delta_mean],
                ],
                fmt="o",
                color=COLORS[condition],
                markeredgecolor="black",
                markeredgewidth=0.45,
                capsize=2.5,
                linewidth=1.5,
            )
        axis.axvline(0, color="#555555", linewidth=1, linestyle="--")
        axis.grid(axis="x", color="#DDDDDD", linewidth=0.7)
        axis.set_title(DIMENSION_LABELS[dimension], fontsize=12, weight="bold")
        axis.set_xlim(-4.5, 4.5)
        axis.set_yticks(range(len(groups)))
        axis.set_yticklabels([
            _group_label(feedback, condition)
            for feedback, condition in groups
        ])
    axes[0, 0].invert_yaxis()
    for axis in axes[-1]:
        axis.set_xlabel("Mean final − initial score (1–7 scale)")
    figure.suptitle(
        "Rubric-free pairwise quality change by condition\n"
        "Points are means; bars are 95% task-cluster bootstrap intervals",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.94))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"quality_delta_intervals.{suffix}", dpi=220)
    plt.close(figure)


def plot_score_heatmaps(
    summaries: list[MetricSummary],
    output: Path,
) -> None:
    plt = pyplot()
    lookup = {
        (row.feedback, row.condition, row.dimension): row
        for row in summaries
    }
    groups = _group_order()
    initial = [
        [lookup[(*group, dimension)].initial_mean for dimension in DIMENSIONS]
        for group in groups
    ]
    final = [
        [lookup[(*group, dimension)].final_mean for dimension in DIMENSIONS]
        for group in groups
    ]
    delta = [
        [lookup[(*group, dimension)].delta_mean for dimension in DIMENSIONS]
        for group in groups
    ]
    figure, axes = plt.subplots(1, 3, figsize=(20, 7.2))
    panels = (
        ("Initial s000", initial, "viridis", 1, 7),
        ("Final s010", final, "viridis", 1, 7),
        ("Final − initial", delta, "RdBu_r", -4, 4),
    )
    for axis, (title, matrix, cmap, low, high) in zip(
        axes,
        panels,
        strict=True,
    ):
        image = axis.imshow(matrix, aspect="auto", cmap=cmap, vmin=low, vmax=high)
        axis.set_title(title, fontsize=13, weight="bold")
        axis.set_xticks(range(len(DIMENSIONS)))
        axis.set_xticklabels(
            [DIMENSION_LABELS[value] for value in DIMENSIONS],
            rotation=38,
            ha="right",
        )
        axis.set_yticks(range(len(groups)))
        axis.set_yticklabels([
            _group_label(feedback, condition)
            for feedback, condition in groups
        ])
        for y, row in enumerate(matrix):
            for x, value in enumerate(row):
                axis.text(
                    x,
                    y,
                    f"{value:+.2f}" if title == "Final − initial" else f"{value:.2f}",
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color=(
                        "white"
                        if title != "Final − initial" and value < 3.7
                        else "black"
                    ),
                )
        figure.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    figure.suptitle(
        "Rubric-free pairwise quality audit: panel-mean scores",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"quality_score_heatmaps.{suffix}", dpi=220)
    plt.close(figure)


def plot_preference_rates(
    summaries: list[MetricSummary],
    output: Path,
) -> None:
    plt = pyplot()
    overall = {
        (row.feedback, row.condition): row
        for row in summaries
        if row.dimension == "overall"
    }
    groups = _group_order()
    figure, axes = plt.subplots(1, 2, figsize=(13.5, 6.8), sharey=True)
    rules = (
        ("Majority final win rate", "majority"),
        ("Consensus final win rate", "consensus"),
    )
    for axis, (title, rule) in zip(axes, rules, strict=True):
        for y, group in enumerate(groups):
            row = overall[group]
            if rule == "majority":
                rate = row.majority_final_win_rate
                wins = row.majority_final_wins
                eligible = row.majority_eligible
            else:
                rate = row.consensus_final_win_rate
                wins = row.consensus_final_wins
                eligible = row.consensus_eligible
            assert rate is not None
            axis.barh(y, rate, color=COLORS[group[1]], edgecolor="white")
            axis.text(
                min(rate + 0.015, 0.94),
                y,
                f"{wins}/{eligible}",
                va="center",
                fontsize=9,
            )
        axis.axvline(0.5, color="#555555", linewidth=1, linestyle="--")
        axis.set_xlim(0, 1.02)
        axis.set_xlabel("Fraction favoring final s010")
        axis.set_title(title, fontsize=12, weight="bold")
        axis.grid(axis="x", color="#DDDDDD", linewidth=0.7)
        axis.set_yticks(range(len(groups)))
        axis.set_yticklabels([
            _group_label(feedback, condition)
            for feedback, condition in groups
        ])
    axes[0].invert_yaxis()
    figure.suptitle(
        "Rubric-free panel preference for final versus initial submission\n"
        "Ties are excluded from each displayed denominator",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"pairwise_preference_rates.{suffix}", dpi=220)
    plt.close(figure)


def write_csv(summaries: list[MetricSummary], output: Path) -> None:
    fields = tuple(MetricSummary.__dataclass_fields__)
    with (output / "quality_audit_summary.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in summaries:
            writer.writerow({field: getattr(row, field) for field in fields})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--semi-summary",
        type=Path,
        default=(
            ROOT / "runs/biomnibench-judgments/"
            "luna-top30-semi-r10-rubric-free-final/summary.json"
        ),
    )
    parser.add_argument(
        "--full-summary",
        type=Path,
        default=(
            ROOT / "runs/biomnibench-judgments/"
            "luna-top30-full-r10-rubric-free-final/summary.json"
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
        *load_audit(args.semi_summary, "Semi"),
        *load_audit(args.full_summary, "Full"),
    ]
    summaries = summarize(rows, draws=args.bootstrap_draws)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(summaries, args.output_dir)
    plot_delta_intervals(summaries, args.output_dir)
    plot_score_heatmaps(summaries, args.output_dir)
    plot_preference_rates(summaries, args.output_dir)
    print(f"wrote rubric-free quality audit to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
