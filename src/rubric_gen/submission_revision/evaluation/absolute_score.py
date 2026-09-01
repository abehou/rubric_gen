"""Build and summarize rubric-free absolute scores."""

from __future__ import annotations

from statistics import fmean

from rubric_gen.submission_revision.evaluation.jobs import (
    EvaluationTarget,
    RubricFreeAbsoluteScoreJob,
    _submission_content_sha256,
)


def assignment_reference(
    job: RubricFreeAbsoluteScoreJob,
    judgment: dict[str, object],
) -> dict[str, object]:
    return {
        "assignment_id": job.target.assignment_id,
        "task_id": job.target.task_id,
        "replicate": job.target.replicate,
        "solver_id": job.target.solver_id,
        "condition_id": job.target.condition_id,
        "model": job.model,
        "artifact": job.artifact,
        "submission_id": job.submission.name,
        "submission_content_sha256": _submission_content_sha256(job.submission),
        "judgment_key": job.key,
        "verdict": judgment["verdict"],
    }


def validate_verdict(value: object) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"score", "explanation"}
        or type(value["score"]) is not int
        or not 0 <= value["score"] <= 100
        or type(value["explanation"]) is not str
        or not value["explanation"].strip()
    ):
        raise ValueError("absolute-score judge returned an invalid verdict")


def summarize(
    targets: tuple[EvaluationTarget, ...],
    records: list[dict[str, object]],
    models: tuple[str, ...],
) -> list[dict[str, object]]:
    records_by_key = {
        (
            str(record["assignment_id"]),
            str(record["model"]),
            str(record["artifact"]),
        ): record
        for record in records
    }
    results: list[dict[str, object]] = []
    for target in targets:
        model_scores: dict[str, object] = {}
        for model in models:
            initial_record = records_by_key[
                (target.assignment_id, model, "initial")
            ]
            final_record = records_by_key[
                (target.assignment_id, model, "final")
            ]
            initial_verdict = initial_record["verdict"]
            final_verdict = final_record["verdict"]
            assert isinstance(initial_verdict, dict)
            assert isinstance(final_verdict, dict)
            initial = float(initial_verdict["score"])
            final = float(final_verdict["score"])
            model_scores[model] = {
                "initial": initial,
                "final": final,
                "gain": final - initial,
            }
        initial_mean = fmean(
            float(value["initial"])  # type: ignore[index]
            for value in model_scores.values()
        )
        final_mean = fmean(
            float(value["final"])  # type: ignore[index]
            for value in model_scores.values()
        )
        results.append({
            "assignment_id": target.assignment_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "solver_id": target.solver_id,
            "condition_id": target.condition_id,
            "rubric_policy": target.rubric_policy.value,
            "rubric_free_absolute_scores": {
                "model_scores": model_scores,
                "initial_panel_mean": initial_mean,
                "final_panel_mean": final_mean,
                "panel_mean_gain": final_mean - initial_mean,
            },
        })
    return results
