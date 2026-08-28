"""Build deterministic summaries for original-rubric ensemble results."""

from __future__ import annotations

from statistics import fmean, median

from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS
from rubric_gen.submission_revision.original_rubric_inputs import (
    BOUNDARIES,
    OriginalRubricStudy,
    OriginalRubricTarget,
)


def record_key(record: dict[str, object]) -> tuple[str, str, str]:
    values = (
        record.get("assignment_id"),
        record.get("model"),
        record.get("boundary"),
    )
    if any(type(value) is not str for value in values):
        raise RuntimeError("ensemble record has an invalid identity")
    return str(values[0]), str(values[1]), str(values[2])


def record_sort_key(record: dict[str, object]) -> tuple[str, str, int]:
    assignment_id, model, boundary = record_key(record)
    return assignment_id, model, BOUNDARIES.index(boundary)


def assignment_summaries(
    study: OriginalRubricStudy,
    records: list[dict[str, object]],
) -> dict[str, object]:
    record_map = {record_key(record): record for record in records}
    return {
        target.assignment_id: _assignment_summary(target, record_map)
        for target in study.targets
    }


def _assignment_summary(
    target: OriginalRubricTarget,
    record_map: dict[tuple[str, str, str], dict[str, object]],
) -> dict[str, object]:
    judges: dict[str, dict[str, object]] = {}
    complete_scores: list[tuple[float, float]] = []
    for model in PRIMARY_RH_MODELS:
        initial = record_map.get((target.assignment_id, model, "initial"))
        final = record_map.get((target.assignment_id, model, "final"))
        summary = _judge_summary(initial, final)
        judges[model] = summary
        if summary["status"] == "completed":
            complete_scores.append(
                (float(summary["initial_score"]), float(summary["final_score"]))
            )
    return {
        "task_id": target.task_id,
        "replicate": target.replicate,
        "condition_id": target.condition_id,
        "rubric_sha256": target.rubric_sha256,
        "judges": judges,
        "ensemble": _ensemble_summary(judges, complete_scores),
    }


def _judge_summary(
    initial: dict[str, object] | None,
    final: dict[str, object] | None,
) -> dict[str, object]:
    if (
        initial is None
        or final is None
        or initial.get("status") != "completed"
        or final.get("status") != "completed"
    ):
        return {"status": "incomplete"}
    initial_score = float(initial["score"])
    final_score = float(final["score"])
    delta = final_score - initial_score
    return {
        "status": "completed",
        "initial_score": initial_score,
        "final_score": final_score,
        "delta": delta,
        "winner": _winner(delta),
    }


def _ensemble_summary(
    judges: dict[str, dict[str, object]],
    complete_scores: list[tuple[float, float]],
) -> dict[str, object]:
    if len(complete_scores) != len(PRIMARY_RH_MODELS):
        return {"status": "incomplete"}
    initial_scores = [item[0] for item in complete_scores]
    final_scores = [item[1] for item in complete_scores]
    votes = [str(judges[model]["winner"]) for model in PRIMARY_RH_MODELS]
    initial_mean = fmean(initial_scores)
    final_mean = fmean(final_scores)
    initial_median = float(median(initial_scores))
    final_median = float(median(final_scores))
    return {
        "status": "completed",
        "initial_mean": initial_mean,
        "final_mean": final_mean,
        "mean_delta": final_mean - initial_mean,
        "initial_median": initial_median,
        "final_median": final_median,
        "median_delta": final_median - initial_median,
        "majority_winner": _majority_winner(votes),
        "consensus_winner": votes[0] if len(set(votes)) == 1 else None,
    }


def _winner(delta: float) -> str:
    if delta > 0:
        return "final"
    if delta < 0:
        return "initial"
    return "tie"


def _majority_winner(votes: list[str]) -> str:
    if votes.count("final") >= 2:
        return "final"
    if votes.count("initial") >= 2:
        return "initial"
    return "tie"


def condition_summaries(assignments: dict[str, object]) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for value in assignments.values():
        if type(value) is not dict:
            continue
        ensemble = value.get("ensemble")
        if type(ensemble) is not dict or ensemble.get("status") != "completed":
            continue
        grouped.setdefault(str(value["condition_id"]), []).append(ensemble)
    return {
        condition_id: _condition_summary(rows)
        for condition_id, rows in sorted(grouped.items())
    }


def _condition_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "assignments": len(rows),
        "initial_mean": fmean(float(row["initial_mean"]) for row in rows),
        "final_mean": fmean(float(row["final_mean"]) for row in rows),
        "mean_delta": fmean(float(row["mean_delta"]) for row in rows),
        "final_majority_win_rate": fmean(
            row["majority_winner"] == "final" for row in rows
        ),
    }
