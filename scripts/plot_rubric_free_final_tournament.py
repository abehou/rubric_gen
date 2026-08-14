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

from rubric_gen.submission_revision.rubric_free_tournament import (
    CONDITIONS,
    FACTORS,
    SUMMARY_KIND,
)
from rubric_gen.submission_revision.visualization.backend import pyplot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "figures" / "luna-top30-rubric-free-final-tournament"
VIEWS = ("Pooled", "Semi", "Full")
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
    "semi": "#999999",
    "full": "#228833",
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
    "full_vs_semi": "Full over semi\n(control prompt and rubric)",
}


@dataclass(frozen=True)
class Match:
    task_id: str
    replicate: int
    left_feedback: str
    right_feedback: str
    left: str
    right: str
    winner: str

    @property
    def left_id(self) -> str:
        return f"{self.left_feedback}-{self.left}"

    @property
    def right_id(self) -> str:
        return f"{self.right_feedback}-{self.right}"

    def score(self, candidate_id: str) -> float:
        if candidate_id not in {self.left_id, self.right_id}:
            raise ValueError(f"candidate does not occur in match: {candidate_id}")
        if self.winner == "tie":
            return 0.5
        return float(
            self.winner == ("left" if candidate_id == self.left_id else "right")
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


def load_tournament(path: Path) -> list[Match]:
    summary = _load_json(path)
    totals = summary.get("totals")
    matches = summary.get("matches")
    if (
        summary.get("schema_version") != 1
        or summary.get("kind") != SUMMARY_KIND
        or summary.get("status") != "completed"
        or type(totals) is not dict
        or totals.get("jobs") != 5_040
        or totals.get("completed") != 5_040
        or totals.get("failed") != 0
        or totals.get("pending") != 0
        or type(matches) is not dict
        or len(matches) != 840
    ):
        raise ValueError(f"expected a completed 840-match tournament: {path}")
    output = []
    for match_id, value in sorted(matches.items()):
        if type(match_id) is not str or type(value) is not dict:
            raise ValueError("tournament match identity is invalid")
        panel = value.get("panel")
        left = value.get("left_condition_id")
        right = value.get("right_condition_id")
        left_feedback = value.get("left_feedback_id")
        right_feedback = value.get("right_feedback_id")
        if (
            type(panel) is not dict
            or panel.get("status") != "completed"
            or panel.get("majority_winner") not in {"left", "right", "tie"}
            or left not in CONDITIONS
            or right not in CONDITIONS
            or left_feedback not in {"semi", "full"}
            or right_feedback not in {"semi", "full"}
            or value.get("submission_id") != "s010"
        ):
            raise ValueError(f"invalid tournament match: {match_id}")
        output.append(Match(
            task_id=str(value["task_id"]),
            replicate=int(value["replicate"]),
            left_feedback=str(left_feedback),
            right_feedback=str(right_feedback),
            left=str(left),
            right=str(right),
            winner=str(panel["majority_winner"]),
        ))
    blocks = {(row.task_id, row.replicate) for row in output}
    if len(blocks) != 30 or len({row.task_id for row in output}) != 30 or any(
        sum((row.task_id, row.replicate) == block for row in output) != 28
        for block in blocks
    ):
        raise ValueError("tournament must contain one 28-match block per task")
    return output


def _view_rows(rows: list[Match], view: str) -> list[Match]:
    if view == "Pooled":
        return rows
    feedback = view.lower()
    return [
        row for row in rows
        if row.left_feedback == feedback and row.right_feedback == feedback
    ]


def _condition_scores(rows: list[Match], candidate_id: str) -> list[tuple[str, float]]:
    return [
        (row.task_id, row.score(candidate_id))
        for row in rows
        if candidate_id in {row.left_id, row.right_id}
    ]


def _factor_scores(rows: list[Match], factor: str, level: str) -> list[tuple[str, float]]:
    output = []
    for row in rows:
        for condition, feedback, candidate_id in (
            (row.left, row.left_feedback, row.left_id),
            (row.right, row.right_feedback, row.right_id),
        ):
            if factor == "feedback":
                matches = feedback == level
            else:
                matches = FACTORS[condition][factor] == level
            if matches:
                output.append((row.task_id, row.score(candidate_id)))
    return output


def _controlled_scores(rows: list[Match], contrast: str) -> list[tuple[str, float]]:
    output = []
    for row in rows:
        left_factors = FACTORS[row.left]
        right_factors = FACTORS[row.right]
        if contrast.startswith("dynamic_vs_static"):
            if (
                row.left_feedback != row.right_feedback
                or left_factors["prompt"] != right_factors["prompt"]
            ):
                continue
            if contrast.endswith("given_base") and left_factors["prompt"] != "base":
                continue
            if contrast.endswith("given_diligent") and left_factors["prompt"] != "diligent":
                continue
            target = row.left_id if left_factors["rubric"] == "dynamic" else row.right_id
        elif contrast.startswith("diligent_vs_base"):
            if (
                row.left_feedback != row.right_feedback
                or left_factors["rubric"] != right_factors["rubric"]
            ):
                continue
            if contrast.endswith("given_static") and left_factors["rubric"] != "static":
                continue
            if contrast.endswith("given_dynamic") and left_factors["rubric"] != "dynamic":
                continue
            target = row.left_id if left_factors["prompt"] == "diligent" else row.right_id
        else:
            if row.left != row.right or row.left_feedback == row.right_feedback:
                continue
            target = row.left_id if row.left_feedback == "full" else row.right_id
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
    for view_index, view in enumerate(VIEWS):
        group = _view_rows(rows, view)
        expected = 840 if view == "Pooled" else 180
        if len(group) != expected:
            raise ValueError(f"expected {expected} matches for {view}")
        seed = 20260811 + view_index * 100
        candidate_ids = (
            tuple(
                f"{feedback}-{condition}"
                for feedback in ("semi", "full")
                for condition in CONDITIONS
            )
            if view == "Pooled"
            else tuple(f"{view.lower()}-{condition}" for condition in CONDITIONS)
        )
        for index, candidate_id in enumerate(candidate_ids):
            output.append(_rate(
                view, "condition", candidate_id,
                _condition_scores(group, candidate_id),
                draws=draws, seed=seed + index,
            ))
        marginal = (
            ("rubric", "static"), ("rubric", "dynamic"),
            ("prompt", "base"), ("prompt", "diligent"),
        )
        for index, (factor, level) in enumerate(marginal, start=10):
            output.append(_rate(
                view, "marginal", f"{factor}.{level}",
                _factor_scores(group, factor, level),
                draws=draws, seed=seed + index,
            ))
        if view == "Pooled":
            for index, level in enumerate(("semi", "full"), start=16):
                output.append(_rate(
                    view, "marginal", f"feedback.{level}",
                    _factor_scores(group, "feedback", level),
                    draws=draws, seed=seed + index,
                ))
        contrasts = (*CONTROLLED, "full_vs_semi") if view == "Pooled" else CONTROLLED
        for index, contrast in enumerate(contrasts, start=20):
            output.append(_rate(
                view, "controlled", contrast,
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
    figure, axes = plt.subplots(1, 3, figsize=(20, 7.2), sharey=True)
    for axis, view in zip(axes, VIEWS, strict=True):
        candidate_ids = (
            tuple(
                f"{feedback}-{condition}"
                for feedback in ("semi", "full")
                for condition in CONDITIONS
            )
            if view == "Pooled"
            else tuple(f"{view.lower()}-{condition}" for condition in CONDITIONS)
        )
        for x, candidate_id in enumerate(candidate_ids):
            _feedback, condition = candidate_id.split("-", 1)
            _errorbar(
                axis,
                x,
                lookup[(view, "condition", candidate_id)],
                COLORS[condition],
            )
        axis.axhline(0.5, color="#555555", linewidth=1, linestyle="--")
        axis.set_ylim(0, 1.08)
        axis.set_xticks(range(len(candidate_ids)))
        axis.set_xticklabels([
            (
                f"{candidate_id.split('-', 1)[0].title()} · "
                f"{CONDITION_LABELS[candidate_id.split('-', 1)[1]]}"
                if view == "Pooled"
                else CONDITION_LABELS[candidate_id.split("-", 1)[1]]
            )
            for candidate_id in candidate_ids
        ], rotation=28, ha="right")
        axis.set_title(view, weight="bold")
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
    figure, axes = plt.subplots(2, 3, figsize=(22, 11), sharey=True)
    base_marginal = (
        "rubric.static", "rubric.dynamic", "prompt.base", "prompt.diligent",
    )
    for column, view in enumerate(VIEWS):
        axis = axes[0, column]
        marginal = (
            (*base_marginal, "feedback.semi", "feedback.full")
            if view == "Pooled"
            else base_marginal
        )
        for x, level in enumerate(marginal):
            color = COLORS[level.split(".")[1]]
            _errorbar(axis, x, lookup[(view, "marginal", level)], color)
        axis.set_xticks(range(len(marginal)))
        axis.set_xticklabels([level.split(".")[1].title() for level in marginal])
        axis.set_title(f"{view}: marginal factor rates", weight="bold")

        axis = axes[1, column]
        contrasts = (*CONTROLLED, "full_vs_semi") if view == "Pooled" else CONTROLLED
        for x, contrast in enumerate(contrasts):
            color = (
                "#66CCEE" if contrast.startswith("dynamic")
                else "#228833" if contrast.startswith("full")
                else "#EE7733"
            )
            _errorbar(axis, x, lookup[(view, "controlled", contrast)], color)
        axis.set_xticks(range(len(contrasts)))
        axis.set_xticklabels(
            [CONTROLLED_LABELS[value] for value in contrasts],
            rotation=20,
            ha="right",
        )
        axis.set_title(f"{view}: matched controlled rates", weight="bold")
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
        "--summary",
        type=Path,
        default=(
            judgments
            / "luna-top30-r10-rubric-free-pooled-tournament-with-trace/summary.json"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.bootstrap_draws < 1_000:
        raise ValueError("bootstrap-draws must be at least 1,000")
    rows = load_tournament(args.summary)
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
