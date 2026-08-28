from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import fmean

import matplotlib.pyplot as plt

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.rh_diagnostics import (
    BOUNDARIES,
    EvaluationConfig,
    MechanisticEvaluationRunner,
    load_evaluation_targets,
)
from rubric_gen.submission_revision.rh_outcome_panel import (
    _required_mechanistic_reference,
)


FIGURE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FIGURE_ROOT.parents[1]
EXPERIMENT_PATH = PROJECT_ROOT / "experiments" / "biomnibench-results20.yaml"
OUTPUT_STEM = FIGURE_ROOT / "partial_mechanistic_judge_gap_by_condition"
ASSIGNMENT_CSV = FIGURE_ROOT / "partial_mechanistic_judge_gap_assignments.csv"
CONDITION_CSV = FIGURE_ROOT / "partial_mechanistic_judge_gap_by_condition.csv"

WEAK_MODEL = "gpt-5.6-luna"
STRONG_MODELS = ("gpt-5.6-sol", "claude-opus-5")
REQUIRED_MODELS = (WEAK_MODEL, *STRONG_MODELS)
RUBRIC_ORDER = ("fixed", "offline_elicitation", "online_elicitation")
RUBRIC_LABELS = {
    "fixed": "Static rubric",
    "offline_elicitation": "Offline elicited",
    "online_elicitation": "Online elicited",
}
FEEDBACK_ORDER = ("full", "semi", "score_only", "user_simulator")
FEEDBACK_LABELS = {
    "full": "Full",
    "semi": "Semi",
    "score_only": "Score only",
    "user_simulator": "User simulator",
}
COLORS = {
    "full": "#0072B2",
    "semi": "#E69F00",
    "score_only": "#009E73",
    "user_simulator": "#CC79A7",
}


def load_record_snapshot(record_dir: Path) -> tuple[dict[str, dict[str, object]], str]:
    snapshot_at = datetime.now().astimezone().isoformat(timespec="seconds")
    records: dict[str, dict[str, object]] = {}
    for path in sorted(record_dir.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict):
            continue
        records[path.stem] = value
    return records, snapshot_at


def terminal_jobs_by_assignment(
    jobs: tuple[object, ...],
) -> dict[tuple[str, str, str], list[object]]:
    result: dict[tuple[str, str, str], list[object]] = defaultdict(list)
    for job in jobs:
        if not any(
            binding.role == "terminal_common"
            for binding in job.generation_bindings
        ):
            continue
        result[(job.target.assignment_id, job.boundary, job.model)].append(job)
    return result


def complete_rubric_score(
    target: object,
    jobs: list[object],
    records: dict[str, dict[str, object]],
) -> float | None:
    if not jobs or any(job.key not in records for job in jobs):
        return None
    expected_sha256 = target.final_generation.rubric.content_sha256
    rubric_score: float | None = None
    for job in jobs:
        binding = next(
            binding
            for binding in job.generation_bindings
            if binding.role == "terminal_common"
        )
        if binding.rubric_sha256 != expected_sha256:
            raise RuntimeError("terminal judgment uses the wrong rubric")
        score = records[job.key].get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise RuntimeError("mechanistic record has an invalid score")
        if rubric_score is not None and rubric_score != float(score):
            raise RuntimeError("terminal rubric has conflicting scores")
        rubric_score = float(score)
    return rubric_score


def condition_parts(experiment: object, target: object) -> tuple[str, str]:
    condition = experiment.condition(target.condition_id)
    feedback = str(condition["feedback_policy"])
    rubric = str(condition["rubric_policy"])
    if feedback not in FEEDBACK_ORDER or rubric not in RUBRIC_ORDER:
        raise RuntimeError("results20 condition is outside the expected design")
    return feedback, rubric


def build_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    experiment = load_experiment(EXPERIMENT_PATH)
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=Path(str(experiment.dag["revise"]["output_dir"])),
        paraphrase_dir=Path(str(experiment.dag["paraphrase"]["output_dir"])),
        output_dir=Path(str(experiment.dag["detect"]["output_dir"]))
        / "mechanistic",
        max_concurrency=24,
        resume=True,
    )
    records, snapshot_at = load_record_snapshot(config.output_dir / "records")
    targets = load_evaluation_targets(config)
    runner = MechanisticEvaluationRunner(config, targets)
    jobs = tuple(
        job
        for job in runner._jobs(targets)
        if _required_mechanistic_reference(job)
    )
    terminal_jobs = terminal_jobs_by_assignment(jobs)

    boundaries: dict[tuple[str, str], dict[str, object]] = {}
    complete_boundary_counts = Counter()
    for target in targets:
        feedback, rubric = condition_parts(experiment, target)
        for boundary in BOUNDARIES:
            scores = {
                model: complete_rubric_score(
                    target,
                    terminal_jobs[(target.assignment_id, boundary, model)],
                    records,
                )
                for model in REQUIRED_MODELS
            }
            if any(score is None for score in scores.values()):
                continue
            normalized = {
                model: float(score) for model, score in scores.items()
                if score is not None
            }
            strong_score = fmean(normalized[model] for model in STRONG_MODELS)
            boundaries[(target.assignment_id, boundary)] = {
                "assignment_id": target.assignment_id,
                "task_id": target.task_id,
                "replicate": target.replicate,
                "condition_id": target.condition_id,
                "feedback_type": feedback,
                "rubric_type": rubric,
                "weak_score": normalized[WEAK_MODEL],
                "gpt_score": normalized[STRONG_MODELS[0]],
                "claude_score": normalized[STRONG_MODELS[1]],
                "strong_score": strong_score,
                "weak_minus_strong": normalized[WEAK_MODEL] - strong_score,
            }
            complete_boundary_counts[boundary] += 1

    rows: list[dict[str, object]] = []
    for target in targets:
        initial = boundaries.get((target.assignment_id, "initial"))
        final = boundaries.get((target.assignment_id, "final"))
        if initial is None or final is None:
            continue
        row = {
            key: initial[key]
            for key in (
                "assignment_id",
                "task_id",
                "replicate",
                "condition_id",
                "feedback_type",
                "rubric_type",
            )
        }
        for boundary, values in (("initial", initial), ("final", final)):
            for key in (
                "weak_score",
                "gpt_score",
                "claude_score",
                "strong_score",
                "weak_minus_strong",
            ):
                row[f"{boundary}_{key}"] = values[key]
        row["gap_change"] = (
            float(row["final_weak_minus_strong"])
            - float(row["initial_weak_minus_strong"])
        )
        rows.append(row)

    rows.sort(key=lambda row: str(row["assignment_id"]))
    model_counts = Counter(str(record.get("model")) for record in records.values())
    metadata: dict[str, object] = {
        "snapshot_at": snapshot_at,
        "record_count": len(records),
        "model_counts": dict(sorted(model_counts.items())),
        "complete_initial_boundaries": complete_boundary_counts["initial"],
        "complete_final_boundaries": complete_boundary_counts["final"],
        "complete_paired_assignments": len(rows),
    }
    return rows, metadata


def write_assignment_csv(rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError("no complete paired mechanistic assignments")
    with ASSIGNMENT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def aggregate_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["rubric_type"]), str(row["feedback_type"]))].append(row)
    aggregates: list[dict[str, object]] = []
    for rubric in RUBRIC_ORDER:
        for feedback in FEEDBACK_ORDER:
            group = grouped[(rubric, feedback)]
            if not group:
                raise RuntimeError(f"no paired rows for {rubric} {feedback}")
            aggregates.append({
                "rubric_type": rubric,
                "feedback_type": feedback,
                "n": len(group),
                "initial_weak_score": fmean(
                    float(row["initial_weak_score"]) for row in group
                ),
                "initial_strong_score": fmean(
                    float(row["initial_strong_score"]) for row in group
                ),
                "initial_weak_minus_strong": fmean(
                    float(row["initial_weak_minus_strong"]) for row in group
                ),
                "final_weak_score": fmean(
                    float(row["final_weak_score"]) for row in group
                ),
                "final_strong_score": fmean(
                    float(row["final_strong_score"]) for row in group
                ),
                "final_weak_minus_strong": fmean(
                    float(row["final_weak_minus_strong"]) for row in group
                ),
                "gap_change": fmean(float(row["gap_change"]) for row in group),
            })
    return aggregates


def write_condition_csv(aggregates: list[dict[str, object]]) -> None:
    with CONDITION_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(aggregates[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(aggregates)


def draw_panel(
    axis: plt.Axes,
    rows: list[dict[str, object]],
    aggregates: list[dict[str, object]],
    metric: str,
    title: str,
) -> None:
    by_key = {
        (str(row["rubric_type"]), str(row["feedback_type"])): row
        for row in aggregates
    }
    width = 0.19
    centers = list(range(len(RUBRIC_ORDER)))
    offsets = (-1.5 * width, -0.5 * width, 0.5 * width, 1.5 * width)
    values: list[float] = []
    for feedback, offset in zip(FEEDBACK_ORDER, offsets, strict=True):
        for rubric_index, rubric in enumerate(RUBRIC_ORDER):
            group = [
                row for row in rows
                if row["rubric_type"] == rubric
                and row["feedback_type"] == feedback
            ]
            center = centers[rubric_index] + offset
            count = len(group)
            mean_value = float(by_key[(rubric, feedback)][metric])
            values.append(mean_value)
            axis.bar(
                center,
                mean_value,
                width=width,
                color=COLORS[feedback],
                edgecolor="white",
                linewidth=0.8,
                label=(
                    FEEDBACK_LABELS[feedback]
                    if rubric_index == 0 else None
                ),
                zorder=2,
            )
            axis.annotate(
                f"{mean_value:+.1f}\nn={count}",
                (center, mean_value),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=7.6,
                fontweight="bold",
                rotation=90 if metric != "gap_change" else 0,
                zorder=3,
            )
    axis.axhline(0, color="#333333", linewidth=0.9)
    axis.set_xticks(centers, [RUBRIC_LABELS[item] for item in RUBRIC_ORDER])
    axis.set_title(title, fontsize=12, fontweight="bold")
    axis.grid(axis="y", color="#D8D8D8", linewidth=0.8)
    axis.set_axisbelow(True)
    lower = min(0.0, min(values))
    upper = max(0.0, max(values))
    padding = max(2.0, (upper - lower) * 0.23)
    axis.set_ylim(lower - padding, upper + padding)


def plot(
    rows: list[dict[str, object]],
    aggregates: list[dict[str, object]],
    metadata: dict[str, object],
) -> None:
    figure, axes = plt.subplots(1, 3, figsize=(18, 6.8), sharex=True)
    draw_panel(
        axes[0],
        rows,
        aggregates,
        "initial_weak_minus_strong",
        "Initial boundary",
    )
    draw_panel(
        axes[1],
        rows,
        aggregates,
        "final_weak_minus_strong",
        "Final boundary",
    )
    draw_panel(
        axes[2],
        rows,
        aggregates,
        "gap_change",
        "Change: final minus initial",
    )
    axes[0].set_ylabel("Weak − strong terminal-rubric score (points)")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.87),
        ncol=4,
        frameon=False,
        title="Feedback type",
    )
    figure.suptitle(
        "BioMNIBench results20: partial mechanistic weak-versus-strong gap",
        fontsize=16,
        fontweight="bold",
        y=0.97,
    )
    figure.text(
        0.5,
        0.018,
        "Matched assignments require complete terminal-rubric scores from "
        "GPT-5.6 Luna, GPT-5.6 Sol, and Claude Opus 5 at both boundaries. "
        "Strong = mean(Sol, Claude).\n"
        f"Snapshot {metadata['snapshot_at']} · "
        f"{metadata['record_count']} cached records · "
        f"{metadata['complete_paired_assignments']} paired assignments. "
        "Negative change means the weak-judge advantage shrank.",
        ha="center",
        va="bottom",
        fontsize=8.5,
        color="#444444",
    )
    figure.subplots_adjust(top=0.76, bottom=0.19, left=0.06, right=0.99, wspace=0.18)
    figure.savefig(OUTPUT_STEM.with_suffix(".png"), dpi=240, facecolor="white")
    figure.savefig(OUTPUT_STEM.with_suffix(".pdf"), facecolor="white")


def main() -> None:
    rows, metadata = build_rows()
    aggregates = aggregate_rows(rows)
    write_assignment_csv(rows)
    write_condition_csv(aggregates)
    plot(rows, aggregates, metadata)
    print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
