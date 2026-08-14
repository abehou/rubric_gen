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

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.study import resolve_study_experiment
from rubric_gen.submission_revision.visualization.backend import pyplot


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
    revision_final_score: float
    revision_minus_ensemble: float


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
    revision_final_mean: float
    revision_final_ci_low: float
    revision_final_ci_high: float
    revision_minus_ensemble_mean: float
    revision_minus_ensemble_ci_low: float
    revision_minus_ensemble_ci_high: float


def _load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_revision_final_scores(path: Path) -> dict[str, float]:
    path = path.resolve()
    manifest = read_json_object(path / "study.json", "study manifest")
    records = manifest.get("records")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "rubric-gen-randomized-revision-study"
        or manifest.get("status") != "completed"
        or type(manifest.get("experiment_path")) is not str
        or type(records) is not list
        or len(records) != 360
        or any(type(record) is not dict for record in records)
    ):
        raise ValueError(f"expected a completed 360-assignment study: {path}")
    experiment = load_experiment(Path(str(manifest["experiment_path"])))
    if (
        experiment.experiment_id != manifest.get("experiment_id")
        or experiment.protocol.get("judge_model") != "gpt-5.6-luna"
    ):
        raise ValueError(f"study does not use GPT-5.6-Luna judging: {path}")
    assignments = {
        str(assignment["assignment_id"]): assignment
        for assignment in experiment.assignments
    }
    ledger = {str(record.get("assignment_id")): record for record in records}
    if len(ledger) != 360 or set(ledger) != set(assignments):
        raise ValueError(f"study ledger differs from experiment: {path}")
    output = {}
    for assignment_id, assignment in assignments.items():
        experiment_dir = resolve_study_experiment(
            path,
            ledger[assignment_id],
            assignment,
        ).resolve()
        state = read_json_object(experiment_dir / "state.json", "revision state")
        submission_ids = state.get("submission_ids")
        scores = state.get("scores")
        if (
            type(submission_ids) is not list
            or submission_ids != [f"s{index:03d}" for index in range(11)]
            or type(scores) is not list
            or len(scores) != 11
            or any(type(score) is not int or not 0 <= score <= 100 for score in scores)
        ):
            raise ValueError(f"invalid final revision score: {assignment_id}")
        output[assignment_id] = float(scores[-1])
    return output


def load_ensemble(
    path: Path,
    feedback: str,
    revision_scores: dict[str, float],
) -> list[EnsembleRow]:
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
        revision_final = revision_scores.get(assignment_id)
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
            or revision_final is None
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
            revision_final_score=revision_final,
            revision_minus_ensemble=revision_final - final,
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
    if {row.assignment_id for row in rows} != set(revision_scores):
        raise ValueError(f"revision and ensemble assignments differ: {path}")
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
            revision_low, revision_high = _cluster_interval(
                group,
                "revision_final_score",
                draws=draws,
                seed=seed + 3,
            )
            gap_low, gap_high = _cluster_interval(
                group,
                "revision_minus_ensemble",
                draws=draws,
                seed=seed + 4,
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
                revision_final_mean=fmean(
                    row.revision_final_score for row in group
                ),
                revision_final_ci_low=revision_low,
                revision_final_ci_high=revision_high,
                revision_minus_ensemble_mean=fmean(
                    row.revision_minus_ensemble for row in group
                ),
                revision_minus_ensemble_ci_low=gap_low,
                revision_minus_ensemble_ci_high=gap_high,
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


def plot_revision_minus_ensemble(
    summaries: list[ConditionSummary],
    output: Path,
) -> None:
    plt = pyplot()
    lookup = _lookup(summaries)
    all_lows = [row.revision_minus_ensemble_ci_low for row in summaries]
    all_highs = [row.revision_minus_ensemble_ci_high for row in summaries]
    lower = min(0.0, min(all_lows)) - 8
    upper = max(0.0, max(all_highs)) + 8
    figure, axes = plt.subplots(1, 2, figsize=(14, 6.8), sharey=True)
    positions = list(range(len(CONDITIONS)))
    for axis, feedback in zip(axes, FEEDBACK, strict=True):
        values = [lookup[(feedback, condition)] for condition in CONDITIONS]
        means = [row.revision_minus_ensemble_mean for row in values]
        errors = [
            [
                row.revision_minus_ensemble_mean
                - row.revision_minus_ensemble_ci_low
                for row in values
            ],
            [
                row.revision_minus_ensemble_ci_high
                - row.revision_minus_ensemble_mean
                for row in values
            ],
        ]
        bars = axis.bar(
            positions,
            means,
            yerr=errors,
            capsize=3,
            color=[CONDITION_COLORS[condition] for condition in CONDITIONS],
            edgecolor="white",
        )
        label_padding = 4 if all(value >= 0 for value in means) else 3
        axis.bar_label(bars, fmt="%+.1f", padding=label_padding, fontsize=10)
        axis.axhline(0, color="#555555", linewidth=1)
        axis.set_xticks(positions)
        axis.set_xticklabels([CONDITION_LABELS[value] for value in CONDITIONS])
        axis.set_ylim(lower, upper)
        axis.set_title(f"{feedback} feedback", fontsize=13, weight="bold")
        axis.grid(axis="y", color="#DDDDDD", linewidth=0.7)
        axis.set_axisbelow(True)
    axes[0].set_ylabel(
        "Average GPT-5.6-Luna final score − ensemble final score"
    )
    figure.suptitle(
        "Final revision-judge over-credit proxy by condition\n"
        "Positive values mean GPT-5.6-Luna scored higher than the ensemble",
        fontsize=15,
        weight="bold",
    )
    figure.text(
        0.5,
        0.89,
        "This is judge/rubric disagreement, not an identified reward-hacking rate.",
        ha="center",
        fontsize=10,
        color="#555555",
    )
    figure.tight_layout(rect=(0, 0, 1, 0.85))
    for suffix in ("png", "pdf"):
        figure.savefig(
            output / f"revision_judge_minus_ensemble.{suffix}",
            dpi=220,
        )
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
    parser.add_argument(
        "--semi-study",
        type=Path,
        default=(
            ROOT / "runs/biomnibench-studies/luna-top30-semi-r10"
        ),
    )
    parser.add_argument(
        "--full-study",
        type=Path,
        default=(
            ROOT / "runs/biomnibench-studies/luna-top30-full-r10"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap-draws", type=int, default=10_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.bootstrap_draws < 1_000:
        raise ValueError("bootstrap-draws must be at least 1,000")
    semi_revision_scores = load_revision_final_scores(args.semi_study)
    full_revision_scores = load_revision_final_scores(args.full_study)
    rows = [
        *load_ensemble(args.semi_ensemble, "Semi", semi_revision_scores),
        *load_ensemble(args.full_ensemble, "Full", full_revision_scores),
    ]
    summaries = summarize(rows, draws=args.bootstrap_draws)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_summary(summaries, args.output_dir)
    plot_average_scores(summaries, args.output_dir)
    plot_average_changes(summaries, args.output_dir)
    plot_revision_minus_ensemble(summaries, args.output_dir)
    print(f"wrote ensemble bar plots to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
