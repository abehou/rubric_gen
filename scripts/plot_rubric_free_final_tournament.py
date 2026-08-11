#!/usr/bin/env python3
"""Plot final-submission tournament and controlled factor win rates."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Callable

from rubric_gen.biomnibench.revision.rubric_free_tournament import (
    CONDITIONS,
    FACTORS,
    SUMMARY_KIND,
)
from rubric_gen.biomnibench.visualization.backend import pyplot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "figures" / "luna-top30-rubric-free-final-tournament"
FEEDBACK = ("Semi", "Full")
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
    "static": "#4477AA",
    "dynamic": "#66CCEE",
    "base": "#CC6677",
    "diligent": "#EE7733",
}
CONTROLLED = (
    "dynamic_vs_static",
    "dynamic_vs_static_given_base",
    "dynamic_vs_static_given_diligent",
    "diligent_vs_base",
    "diligent_vs_base_given_static",
    "diligent_vs_base_given_dynamic",
)
CONTROLLED_LABELS = {
    "dynamic_vs_static": "Dynamic over static\n(control prompt)",
    "dynamic_vs_static_given_base": "Dynamic over static\n(base only)",
    "dynamic_vs_static_given_diligent": "Dynamic over static\n(diligent only)",
    "diligent_vs_base": "Diligent over base\n(control rubric)",
    "diligent_vs_base_given_static": "Diligent over base\n(static only)",
    "diligent_vs_base_given_dynamic": "Diligent over base\n(dynamic only)",
}


@dataclass(frozen=True)
class Match:
    feedback: str
    task_id: str
    replicate: int
    left: str
    right: str
    winner: str

    def score(self, condition: str) -> float:
        if condition not in {self.left, self.right}:
            raise ValueError(f"condition does not occur in match: {condition}")
        if self.winner == "tie":
            return 0.5
        return float(
            self.winner == ("left" if condition == self.left else "right")
        )


@dataclass(frozen=True)
class Rate:
    feedback: str
    analysis: str
    level: str
    comparisons: int
    wins: int
    ties: int
    losses: int
    half_win_rate: float
    ci_low: float
    ci_high: float


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_tournament(path: Path, feedback: str) -> list[Match]:
    summary = _load_json(path)
    totals = summary.get("totals")
    matches = summary.get("matches")
    if (
        summary.get("schema_version") != 1
        or summary.get("kind") != SUMMARY_KIND
        or summary.get("status") != "completed"
        or type(totals) is not dict
        or totals.get("jobs") != 3_240
        or totals.get("completed") != 3_240
        or totals.get("failed") != 0
        or totals.get("pending") != 0
        or type(matches) is not dict
        or len(matches) != 540
    ):
        raise ValueError(f"expected a completed 540-match tournament: {path}")
    output = []
    for match_id, value in sorted(matches.items()):
        if type(match_id) is not str or type(value) is not dict:
            raise ValueError("tournament match identity is invalid")
        panel = value.get("panel")
        left = value.get("left_condition_id")
        right = value.get("right_condition_id")
        if (
            type(panel) is not dict
            or panel.get("status") != "completed"
            or panel.get("majority_winner") not in {"left", "right", "tie"}
            or left not in CONDITIONS
            or right not in CONDITIONS
            or CONDITIONS.index(str(left)) >= CONDITIONS.index(str(right))
            or value.get("submission_id") != "s010"
        ):
            raise ValueError(f"invalid tournament match: {match_id}")
        output.append(Match(
            feedback=feedback,
            task_id=str(value["task_id"]),
            replicate=int(value["replicate"]),
            left=str(left),
            right=str(right),
            winner=str(panel["majority_winner"]),
        ))
    blocks = {(row.task_id, row.replicate) for row in output}
    if len(blocks) != 90 or any(
        sum((row.task_id, row.replicate) == block for row in output) != 6
        for block in blocks
    ):
        raise ValueError("tournament must contain 90 complete six-match blocks")
    return output


def _condition_scores(rows: list[Match], condition: str) -> list[tuple[str, float]]:
    return [
        (row.task_id, row.score(condition))
        for row in rows
        if condition in {row.left, row.right}
    ]


def _factor_scores(rows: list[Match], factor: str, level: str) -> list[tuple[str, float]]:
    output = []
    for row in rows:
        for condition in (row.left, row.right):
            if FACTORS[condition][factor] == level:
                output.append((row.task_id, row.score(condition)))
    return output


def _controlled_scores(rows: list[Match], contrast: str) -> list[tuple[str, float]]:
    output = []
    for row in rows:
        left_factors = FACTORS[row.left]
        right_factors = FACTORS[row.right]
        if contrast.startswith("dynamic_vs_static"):
            if left_factors["prompt"] != right_factors["prompt"]:
                continue
            if contrast.endswith("given_base") and left_factors["prompt"] != "base":
                continue
            if contrast.endswith("given_diligent") and left_factors["prompt"] != "diligent":
                continue
            target = row.left if left_factors["rubric"] == "dynamic" else row.right
        else:
            if left_factors["rubric"] != right_factors["rubric"]:
                continue
            if contrast.endswith("given_static") and left_factors["rubric"] != "static":
                continue
            if contrast.endswith("given_dynamic") and left_factors["rubric"] != "dynamic":
                continue
            target = row.left if left_factors["prompt"] == "diligent" else row.right
        output.append((row.task_id, row.score(target)))
    return output


def _task_interval(
    scores: list[tuple[str, float]], *, draws: int, seed: int
) -> tuple[float, float]:
    by_task: dict[str, list[float]] = defaultdict(list)
    for task, score in scores:
        by_task[task].append(score)
    tasks = sorted(by_task)
    if len(tasks) != 30:
        raise ValueError("each estimate must contain all 30 tasks")
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sample = [tasks[rng.randrange(len(tasks))] for _task in tasks]
        estimates.append(fmean(score for task in sample for score in by_task[task]))
    estimates.sort()
    return (
        estimates[int(0.025 * (draws - 1))],
        estimates[int(0.975 * (draws - 1))],
    )


def _rate(
    feedback: str,
    analysis: str,
    level: str,
    scores: list[tuple[str, float]],
    *,
    draws: int,
    seed: int,
) -> Rate:
    values = [score for _task, score in scores]
    low, high = _task_interval(scores, draws=draws, seed=seed)
    return Rate(
        feedback=feedback,
        analysis=analysis,
        level=level,
        comparisons=len(values),
        wins=values.count(1.0),
        ties=values.count(0.5),
        losses=values.count(0.0),
        half_win_rate=fmean(values),
        ci_low=low,
        ci_high=high,
    )


def summarize(rows: list[Match], *, draws: int) -> list[Rate]:
    output = []
    for feedback_index, feedback in enumerate(FEEDBACK):
        group = [row for row in rows if row.feedback == feedback]
        if len(group) != 540:
            raise ValueError(f"expected 540 matches for {feedback}")
        seed = 20260811 + feedback_index * 100
        for index, condition in enumerate(CONDITIONS):
            output.append(_rate(
                feedback, "condition", condition,
                _condition_scores(group, condition),
                draws=draws, seed=seed + index,
            ))
        marginal = (
            ("rubric", "static"), ("rubric", "dynamic"),
            ("prompt", "base"), ("prompt", "diligent"),
        )
        for index, (factor, level) in enumerate(marginal, start=10):
            output.append(_rate(
                feedback, "marginal", f"{factor}.{level}",
                _factor_scores(group, factor, level),
                draws=draws, seed=seed + index,
            ))
        for index, contrast in enumerate(CONTROLLED, start=20):
            output.append(_rate(
                feedback, "controlled", contrast,
                _controlled_scores(group, contrast),
                draws=draws, seed=seed + index,
            ))
    return output


def _errorbar(axis: object, x: int, row: Rate, color: str) -> None:
    axis.errorbar(
        x,
        row.half_win_rate,
        yerr=[[row.half_win_rate - row.ci_low], [row.ci_high - row.half_win_rate]],
        fmt="o",
        color=color,
        markeredgecolor="black",
        markeredgewidth=0.45,
        capsize=3,
        linewidth=1.5,
    )
    axis.text(
        x,
        min(row.ci_high + 0.035, 1.02),
        f"{row.wins}W {row.ties}T {row.losses}L",
        ha="center",
        va="bottom",
        fontsize=7.5,
        rotation=90,
    )


def plot_condition_rates(rates: list[Rate], output: Path) -> None:
    plt = pyplot()
    lookup = {(row.feedback, row.analysis, row.level): row for row in rates}
    figure, axes = plt.subplots(1, 2, figsize=(13.5, 6.8), sharey=True)
    for axis, feedback in zip(axes, FEEDBACK, strict=True):
        for x, condition in enumerate(CONDITIONS):
            _errorbar(axis, x, lookup[(feedback, "condition", condition)], COLORS[condition])
        axis.axhline(0.5, color="#555555", linewidth=1, linestyle="--")
        axis.set_ylim(0, 1.08)
        axis.set_xticks(range(4))
        axis.set_xticklabels([CONDITION_LABELS[value] for value in CONDITIONS], rotation=22)
        axis.set_title(f"{feedback} feedback", weight="bold")
        axis.set_ylabel("Round-robin win rate")
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.7)
    figure.suptitle(
        "Final s010 submission quality across all opponents\n"
        "Ties count as half a win; bars are 95% task-cluster bootstrap intervals",
        fontsize=14,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.92))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"final_condition_round_robin.{suffix}", dpi=220)
    plt.close(figure)


def plot_factor_rates(rates: list[Rate], output: Path) -> None:
    plt = pyplot()
    lookup = {(row.feedback, row.analysis, row.level): row for row in rates}
    figure, axes = plt.subplots(2, 2, figsize=(16, 11), sharey=True)
    marginal = ("rubric.static", "rubric.dynamic", "prompt.base", "prompt.diligent")
    for column, feedback in enumerate(FEEDBACK):
        axis = axes[0, column]
        for x, level in enumerate(marginal):
            color = COLORS[level.split(".")[1]]
            _errorbar(axis, x, lookup[(feedback, "marginal", level)], color)
        axis.set_xticks(range(4))
        axis.set_xticklabels(("Static", "Dynamic", "Base", "Diligent"))
        axis.set_title(f"{feedback}: marginal factor rates", weight="bold")

        axis = axes[1, column]
        for x, contrast in enumerate(CONTROLLED):
            color = "#66CCEE" if contrast.startswith("dynamic") else "#EE7733"
            _errorbar(axis, x, lookup[(feedback, "controlled", contrast)], color)
        axis.set_xticks(range(6))
        axis.set_xticklabels(
            [CONTROLLED_LABELS[value] for value in CONTROLLED],
            rotation=20,
            ha="right",
        )
        axis.set_title(f"{feedback}: matched controlled rates", weight="bold")
    for axis in axes.flat:
        axis.axhline(0.5, color="#555555", linewidth=1, linestyle="--")
        axis.set_ylim(0, 1.08)
        axis.set_ylabel("Win rate")
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.7)
    figure.suptitle(
        "Which experimental factor produces stronger final submissions?\n"
        "Controlled rates compare factor levels within the same task, replicate, and other factor",
        fontsize=14,
        weight="bold",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.93))
    for suffix in ("png", "pdf"):
        figure.savefig(output / f"final_factor_win_rates.{suffix}", dpi=220)
    plt.close(figure)


def write_csv(rates: list[Rate], output: Path) -> None:
    fields = tuple(Rate.__dataclass_fields__)
    with (output / "final_tournament_win_rates.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rates:
            writer.writerow({field: getattr(row, field) for field in fields})


def build_parser() -> argparse.ArgumentParser:
    judgments = ROOT / "runs" / "biomnibench-judgments"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--semi-summary",
        type=Path,
        default=judgments / "luna-top30-semi-r10-rubric-free-tournament/summary.json",
    )
    parser.add_argument(
        "--full-summary",
        type=Path,
        default=judgments / "luna-top30-full-r10-rubric-free-tournament/summary.json",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.bootstrap_draws < 1_000:
        raise ValueError("bootstrap-draws must be at least 1,000")
    rows = [
        *load_tournament(args.semi_summary, "Semi"),
        *load_tournament(args.full_summary, "Full"),
    ]
    rates = summarize(rows, draws=args.bootstrap_draws)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(rates, args.output_dir)
    plot_condition_rates(rates, args.output_dir)
    plot_factor_rates(rates, args.output_dir)
    print(f"wrote final tournament analysis to {args.output_dir}")
    print(
        "keep the separate s000-versus-s010 plots from "
        "scripts/plot_rubric_free_quality_audit.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
