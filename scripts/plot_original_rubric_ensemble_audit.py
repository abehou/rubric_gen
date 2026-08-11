#!/usr/bin/env python3
"""Plot completed original-rubric ensemble results and joined quality scores."""

from __future__ import annotations

import argparse
import csv
import json
import math
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
    "base-static": "Base · Static",
    "base-prospective": "Base · Dynamic",
    "diligent-static": "Diligent · Static",
    "diligent-prospective": "Diligent · Dynamic",
}
COLORS = {
    "base-static": "#4477AA",
    "base-prospective": "#66CCEE",
    "diligent-static": "#CC6677",
    "diligent-prospective": "#EE7733",
}
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
    majority_winner: str
    consensus_winner: str | None


@dataclass(frozen=True)
class QualityRow:
    feedback: str
    assignment_id: str
    task_id: str
    replicate: int
    condition: str
    final_scores: dict[str, float]
    score_deltas: dict[str, float]


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
            or ensemble.get("majority_winner") not in {"initial", "final", "tie"}
            or ensemble.get("consensus_winner") not in {
                "initial", "final", "tie", None
            }
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
            or abs(initial - fmean(float(judge["initial_score"]) for judge in judges.values())) > 1e-9
            or abs(final - fmean(float(judge["final_score"]) for judge in judges.values())) > 1e-9
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
            majority_winner=str(ensemble["majority_winner"]),
            consensus_winner=ensemble["consensus_winner"],
        ))
    _validate_grid(rows, path)
    return rows


def _quality_score_map(value: object, label: str) -> dict[str, float]:
    if type(value) is not dict or set(value) != set(DIMENSIONS):
        raise ValueError(f"invalid quality scores: {label}")
    scores = {dimension: float(value[dimension]) for dimension in DIMENSIONS}
    if any(not 1 <= score <= 7 for score in scores.values()):
        raise ValueError(f"quality score is outside 1–7: {label}")
    return scores


def load_quality(path: Path, feedback: str) -> list[QualityRow]:
    summary = _load_json(path)
    totals = summary.get("totals")
    assignments = summary.get("assignments")
    if (
        summary.get("schema_version") != 1
        or summary.get("kind") != "rubric-free-pairwise-final-evaluation"
        or summary.get("status") != "completed"
        or type(totals) is not dict
        or totals.get("completed") != 2_160
        or totals.get("failed") != 0
        or totals.get("pending") != 0
        or type(assignments) is not dict
        or len(assignments) != 360
    ):
        raise ValueError(f"expected a completed rubric-free quality audit: {path}")
    rows = []
    for assignment_id, assignment in sorted(assignments.items()):
        if type(assignment_id) is not str or type(assignment) is not dict:
            raise ValueError("quality assignment identity is invalid")
        panel = assignment.get("panel")
        condition = assignment.get("condition_id")
        if (
            condition not in CONDITIONS
            or type(panel) is not dict
            or panel.get("status") != "completed"
        ):
            raise ValueError(f"invalid quality panel: {assignment_id}")
        final = _quality_score_map(
            panel.get("final_mean_scores"),
            f"{assignment_id} final",
        )
        delta = panel.get("mean_score_deltas")
        if type(delta) is not dict or set(delta) != set(DIMENSIONS):
            raise ValueError(f"invalid quality deltas: {assignment_id}")
        rows.append(QualityRow(
            feedback=feedback,
            assignment_id=assignment_id,
            task_id=str(assignment["task_id"]),
            replicate=int(assignment["replicate"]),
            condition=str(condition),
            final_scores=final,
            score_deltas={key: float(delta[key]) for key in DIMENSIONS},
        ))
    _validate_grid(rows, path)
    return rows


def _validate_grid(rows: list[object], path: Path) -> None:
    keys = {
        (row.task_id, row.replicate, row.condition)
        for row in rows
    }
    if len(rows) != 360 or len(keys) != 360:
        raise ValueError(f"expected 360 unique assignments: {path}")
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row.condition] += 1
    if counts != {condition: 90 for condition in CONDITIONS}:
        raise ValueError(f"expected 90 assignments per condition: {path}")


def _group_order() -> list[tuple[str, str]]:
    return [
        (feedback, condition)
        for feedback in FEEDBACK
        for condition in CONDITIONS
    ]


def _group_label(group: tuple[str, str]) -> str:
    return f"{group[0]} · {CONDITION_LABELS[group[1]]}"


def _cluster_interval(
    rows: list[EnsembleRow],
    *,
    draws: int,
    seed: int,
) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[row.task_id].append(row.score_delta)
    tasks = sorted(by_task)
    if len(tasks) != 30 or any(len(by_task[task]) != 3 for task in tasks):
        raise ValueError("each condition must contain 30 tasks and 3 replicates")
    rng = random.Random(seed)
    samples = []
    for _ in range(draws):
        selected = [tasks[rng.randrange(len(tasks))] for _task in tasks]
        samples.append(fmean(
            value
            for task in selected
            for value in by_task[task]
        ))
    samples.sort()
    return (
        samples[int(0.025 * (draws - 1))],
        samples[int(0.975 * (draws - 1))],
    )


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x, mean_y = fmean(xs), fmean(ys)
    x_var = sum((value - mean_x) ** 2 for value in xs)
    y_var = sum((value - mean_y) ** 2 for value in ys)
    if x_var == 0 or y_var == 0:
        return None
    return sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(xs, ys, strict=True)
    ) / math.sqrt(x_var * y_var)


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for index in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _joined_rows(
    ensemble_rows: list[EnsembleRow],
    quality_rows: list[QualityRow],
) -> list[tuple[EnsembleRow, QualityRow]]:
    quality = {
        (row.feedback, row.assignment_id): row
        for row in quality_rows
    }
    if len(quality) != 720:
        raise ValueError("quality audit contains duplicate joined identities")
    output = []
    for ensemble in ensemble_rows:
        key = ensemble.feedback, ensemble.assignment_id
        row = quality.get(key)
        if row is None:
            raise ValueError(f"quality result is missing: {key}")
        if (
            row.task_id != ensemble.task_id
            or row.replicate != ensemble.replicate
            or row.condition != ensemble.condition
        ):
            raise ValueError(f"joined assignment metadata changed: {key}")
        output.append((ensemble, row))
    if len(output) != 720:
        raise ValueError("expected 720 joined ensemble and quality results")
    return output


def write_summaries(
    rows: list[EnsembleRow],
    joined: list[tuple[EnsembleRow, QualityRow]],
    output: Path,
    *,
    draws: int,
) -> None:
    grouped: dict[tuple[str, str], list[EnsembleRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.feedback, row.condition)].append(row)
    with (output / "ensemble_score_summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        fields = (
            "feedback", "condition", "assignments", "tasks", "initial_mean",
            "final_mean", "delta_mean", "delta_ci_low", "delta_ci_high",
            "final_score_100", "final_score_at_least_95", "majority_eligible",
            "majority_final_wins", "majority_final_win_rate",
            "consensus_eligible", "consensus_final_wins",
            "consensus_final_win_rate",
        )
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, group_key in enumerate(_group_order()):
            group = grouped[group_key]
            low, high = _cluster_interval(
                group,
                draws=draws,
                seed=20260811 + index,
            )
            majority = [row for row in group if row.majority_winner != "tie"]
            consensus = [
                row
                for row in group
                if row.consensus_winner in {"initial", "final"}
            ]
            majority_wins = sum(row.majority_winner == "final" for row in majority)
            consensus_wins = sum(row.consensus_winner == "final" for row in consensus)
            writer.writerow({
                "feedback": group_key[0],
                "condition": group_key[1],
                "assignments": len(group),
                "tasks": len({row.task_id for row in group}),
                "initial_mean": fmean(row.initial_score for row in group),
                "final_mean": fmean(row.final_score for row in group),
                "delta_mean": fmean(row.score_delta for row in group),
                "delta_ci_low": low,
                "delta_ci_high": high,
                "final_score_100": sum(row.final_score == 100 for row in group),
                "final_score_at_least_95": sum(row.final_score >= 95 for row in group),
                "majority_eligible": len(majority),
                "majority_final_wins": majority_wins,
                "majority_final_win_rate": majority_wins / len(majority),
                "consensus_eligible": len(consensus),
                "consensus_final_wins": consensus_wins,
                "consensus_final_win_rate": consensus_wins / len(consensus),
            })
    grouped_joined: dict[
        tuple[str, str], list[tuple[EnsembleRow, QualityRow]]
    ] = defaultdict(list)
    for pair in joined:
        grouped_joined[(pair[0].feedback, pair[0].condition)].append(pair)
    with (output / "quality_vs_original_rubric_correlations.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        fields = (
            "feedback", "condition", "dimension", "assignments",
            "pearson_r", "spearman_r", "original_final_mean",
            "quality_final_mean",
        )
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for group_key in _group_order():
            group = grouped_joined[group_key]
            xs = [ensemble.final_score for ensemble, _quality in group]
            for dimension in DIMENSIONS:
                ys = [quality.final_scores[dimension] for _ensemble, quality in group]
                writer.writerow({
                    "feedback": group_key[0],
                    "condition": group_key[1],
                    "dimension": dimension,
                    "assignments": len(group),
                    "pearson_r": _pearson(xs, ys),
                    "spearman_r": _pearson(_ranks(xs), _ranks(ys)),
                    "original_final_mean": fmean(xs),
                    "quality_final_mean": fmean(ys),
                })


def plot_ensemble_heatmap(rows: list[EnsembleRow], output: Path) -> None:
    plt = pyplot()
    grouped: dict[tuple[str, str], list[EnsembleRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.feedback, row.condition)].append(row)
    groups = _group_order()
    matrix = [[
        fmean(row.initial_score for row in grouped[group]),
        fmean(row.final_score for row in grouped[group]),
        fmean(row.score_delta for row in grouped[group]),
    ] for group in groups]
    figure, axis = plt.subplots(figsize=(9.5, 7.2))
    image = axis.imshow(matrix, aspect="auto", cmap="viridis", vmin=0, vmax=100)
    axis.set_xticks(range(3))
    axis.set_xticklabels(("Initial s000", "Final s010", "Final − initial"))
    axis.set_yticks(range(len(groups)))
    axis.set_yticklabels([_group_label(group) for group in groups])
    for y, values in enumerate(matrix):
        for x, value in enumerate(values):
            axis.text(
                x, y, f"{value:.1f}", ha="center", va="center",
                color="white" if value < 48 else "black", fontsize=10,
            )
    figure.colorbar(image, ax=axis, label="Original-rubric ensemble score (0–100)")
    axis.set_title(
        "Original-rubric ensemble scores by condition",
        fontsize=15,
        weight="bold",
        pad=16,
    )
    figure.tight_layout()
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"original_rubric_score_heatmap.{suffix}", dpi=220)
    plt.close(figure)


def plot_delta_intervals(
    rows: list[EnsembleRow],
    output: Path,
    *,
    draws: int,
) -> None:
    plt = pyplot()
    grouped: dict[tuple[str, str], list[EnsembleRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.feedback, row.condition)].append(row)
    groups = _group_order()
    figure, axis = plt.subplots(figsize=(10.5, 6.8))
    for index, group_key in enumerate(groups):
        group = grouped[group_key]
        mean = fmean(row.score_delta for row in group)
        low, high = _cluster_interval(
            group,
            draws=draws,
            seed=20260811 + index,
        )
        axis.errorbar(
            mean,
            index,
            xerr=[[mean - low], [high - mean]],
            fmt="o",
            color=COLORS[group_key[1]],
            markeredgecolor="black",
            markeredgewidth=0.5,
            capsize=3,
            linewidth=1.6,
        )
    axis.axvline(0, color="#555555", linewidth=1, linestyle="--")
    axis.set_yticks(range(len(groups)))
    axis.set_yticklabels([_group_label(group) for group in groups])
    axis.invert_yaxis()
    axis.set_xlabel("Mean final − initial original-rubric score")
    axis.grid(axis="x", color="#DDDDDD", linewidth=0.7)
    axis.set_title(
        "Original-rubric ensemble improvement by condition\n"
        "Bars are 95% task-cluster bootstrap intervals",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout()
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"original_rubric_delta_intervals.{suffix}", dpi=220)
    plt.close(figure)


def plot_preference_rates(rows: list[EnsembleRow], output: Path) -> None:
    plt = pyplot()
    grouped: dict[tuple[str, str], list[EnsembleRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.feedback, row.condition)].append(row)
    groups = _group_order()
    figure, axes = plt.subplots(1, 2, figsize=(13.5, 6.8), sharey=True)
    rules = (
        ("Majority final win rate", "majority"),
        ("Consensus final win rate", "consensus"),
    )
    for axis, (title, rule) in zip(axes, rules, strict=True):
        for y, group_key in enumerate(groups):
            group = grouped[group_key]
            if rule == "majority":
                eligible = [row for row in group if row.majority_winner != "tie"]
                wins = sum(row.majority_winner == "final" for row in eligible)
            else:
                eligible = [
                    row
                    for row in group
                    if row.consensus_winner in {"initial", "final"}
                ]
                wins = sum(row.consensus_winner == "final" for row in eligible)
            rate = wins / len(eligible)
            axis.barh(
                y,
                rate,
                color=COLORS[group_key[1]],
                edgecolor="white",
            )
            axis.text(
                min(rate + 0.012, 0.94),
                y,
                f"{wins}/{len(eligible)}",
                va="center",
                fontsize=9,
            )
        axis.axvline(0.5, color="#555555", linewidth=1, linestyle="--")
        axis.set_xlim(0, 1.02)
        axis.set_xlabel("Fraction favoring final s010")
        axis.set_title(title, fontsize=12, weight="bold")
        axis.grid(axis="x", color="#DDDDDD", linewidth=0.7)
        axis.set_yticks(range(len(groups)))
        axis.set_yticklabels([_group_label(group) for group in groups])
    axes[0].invert_yaxis()
    figure.suptitle(
        "Original-rubric ensemble preference for final submission\n"
        "Ties are excluded from each displayed denominator",
        fontsize=15,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    for suffix in ("png", "pdf"):
        figure.savefig(
            output / f"original_rubric_preference_rates.{suffix}",
            dpi=220,
        )
    plt.close(figure)


def plot_quality_join(
    joined: list[tuple[EnsembleRow, QualityRow]],
    output: Path,
) -> None:
    plt = pyplot()
    grouped: dict[
        tuple[str, str], list[tuple[EnsembleRow, QualityRow]]
    ] = defaultdict(list)
    for pair in joined:
        grouped[(pair[0].feedback, pair[0].condition)].append(pair)
    figure, axes = plt.subplots(
        len(DIMENSIONS),
        len(FEEDBACK),
        figsize=(14.5, 22),
        sharex=True,
        sharey="row",
    )
    for row_index, dimension in enumerate(DIMENSIONS):
        for column_index, feedback in enumerate(FEEDBACK):
            axis = axes[row_index, column_index]
            for condition in CONDITIONS:
                group = grouped[(feedback, condition)]
                xs = [ensemble.final_score for ensemble, _quality in group]
                ys = [quality.final_scores[dimension] for _ensemble, quality in group]
                axis.scatter(
                    xs,
                    ys,
                    s=24,
                    alpha=0.48,
                    color=COLORS[condition],
                    edgecolors="none",
                    label=CONDITION_LABELS[condition],
                )
                mean_x = fmean(xs)
                mean_y = fmean(ys)
                denominator = sum((value - mean_x) ** 2 for value in xs)
                if denominator > 0:
                    slope = sum(
                        (x - mean_x) * (y - mean_y)
                        for x, y in zip(xs, ys, strict=True)
                    ) / denominator
                    intercept = mean_y - slope * mean_x
                    low, high = min(xs), max(xs)
                    axis.plot(
                        [low, high],
                        [intercept + slope * low, intercept + slope * high],
                        color=COLORS[condition],
                        linewidth=1.5,
                    )
            axis.set_xlim(-2, 102)
            axis.set_ylim(0.8, 7.2)
            axis.grid(color="#E1E1E1", linewidth=0.6)
            if row_index == 0:
                axis.set_title(f"{feedback} feedback", fontsize=13, weight="bold")
            if column_index == 0:
                axis.set_ylabel(DIMENSION_LABELS[dimension] + " (1–7)")
            if row_index == len(DIMENSIONS) - 1:
                axis.set_xlabel("Final original-rubric ensemble score (0–100)")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.977),
    )
    figure.suptitle(
        "Final rubric-free quality versus final original-rubric score\n"
        "Points are assignments; lines are condition-specific linear fits",
        fontsize=16,
        weight="bold",
        y=0.997,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.956))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"final_quality_vs_original_rubric.{suffix}", dpi=220)
    plt.close(figure)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    judgments = ROOT / "runs" / "biomnibench-judgments"
    parser.add_argument(
        "--semi-ensemble",
        type=Path,
        default=judgments / "luna-top30-semi-r10-original-rubric-deduplicated/summary.json",
    )
    parser.add_argument(
        "--full-ensemble",
        type=Path,
        default=judgments / "luna-top30-full-r10-original-rubric-deduplicated/summary.json",
    )
    parser.add_argument(
        "--semi-quality",
        type=Path,
        default=(
            judgments
            / "luna-top30-semi-r10-rubric-free-final-with-trace/summary.json"
        ),
    )
    parser.add_argument(
        "--full-quality",
        type=Path,
        default=(
            judgments
            / "luna-top30-full-r10-rubric-free-final-with-trace/summary.json"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.bootstrap_draws < 1_000:
        raise ValueError("bootstrap-draws must be at least 1,000")
    ensemble_rows = [
        *load_ensemble(args.semi_ensemble, "Semi"),
        *load_ensemble(args.full_ensemble, "Full"),
    ]
    quality_rows = [
        *load_quality(args.semi_quality, "Semi"),
        *load_quality(args.full_quality, "Full"),
    ]
    joined = _joined_rows(ensemble_rows, quality_rows)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_summaries(
        ensemble_rows,
        joined,
        args.output_dir,
        draws=args.bootstrap_draws,
    )
    plot_ensemble_heatmap(ensemble_rows, args.output_dir)
    plot_delta_intervals(
        ensemble_rows,
        args.output_dir,
        draws=args.bootstrap_draws,
    )
    plot_preference_rates(ensemble_rows, args.output_dir)
    plot_quality_join(joined, args.output_dir)
    print(f"wrote original-rubric ensemble audit to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
