"""Build and summarize initial-versus-final preference scores."""

from __future__ import annotations

from statistics import fmean

from rubric_gen.submission_revision.evaluation.jobs import (
    EvaluationTarget,
    PairwisePreferenceJob,
    _submission_content_sha256,
)


def assignment_reference(
    job: PairwisePreferenceJob,
    judgment: dict[str, object],
) -> dict[str, object]:
    target = job.target
    return {
        "assignment_id": target.assignment_id,
        "task_id": target.task_id,
        "replicate": target.replicate,
        "solver_id": target.solver_id,
        "condition_id": target.condition_id,
        "model": job.model,
        "order": job.order,
        "initial_submission_id": target.submission_ids[0],
        "final_submission_id": target.submission_ids[-1],
        "initial_content_sha256": _submission_content_sha256(
            target.initial_submission
        ),
        "final_content_sha256": _submission_content_sha256(
            target.final_submission
        ),
        "judgment_key": job.key,
        "verdict": judgment["verdict"],
    }


def validate_verdict(value: object) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"preferred_response", "explanation"}
        or type(value["preferred_response"]) is not str
        or value["preferred_response"] not in {"response_A", "response_B", "tie"}
        or type(value["explanation"]) is not str
        or not value["explanation"].strip()
    ):
        raise ValueError("pairwise-preference judge returned an invalid verdict")


def _final_preference_score(order: str, preferred: object) -> float:
    if preferred not in {"response_A", "response_B", "tie"}:
        raise RuntimeError("pairwise preference record has an invalid decision")
    if preferred == "tie":
        return 0.5
    final_response = "response_B" if order == "initial-first" else "response_A"
    return 1.0 if preferred == final_response else 0.0


def summarize(
    targets: tuple[EvaluationTarget, ...],
    records: list[dict[str, object]],
    models: tuple[str, ...],
    order_plan: dict[tuple[str, int], str],
) -> list[dict[str, object]]:
    records_by_key = {
        (str(record["assignment_id"]), str(record["model"])): record
        for record in records
    }
    results: list[dict[str, object]] = []
    for target in targets:
        same_artifact = target.initial_and_final_match()
        order = order_plan[(target.task_id, target.replicate)]
        model_results: dict[str, object] = {}
        for model in models:
            if same_artifact:
                model_results[model] = {
                    "status": "same_artifact",
                    "score": 0.5,
                }
                continue
            record = records_by_key[(target.assignment_id, model)]
            if record.get("order") != order:
                raise RuntimeError("pairwise preference record has the wrong order")
            verdict = record["verdict"]
            if not isinstance(verdict, dict):
                raise RuntimeError("pairwise preference record has an invalid verdict")
            preferred = verdict.get("preferred_response")
            model_results[model] = {
                "status": "completed",
                "order": order,
                "decision": preferred,
                "score": _final_preference_score(order, preferred),
            }
        panel_mean = fmean(
            float(value["score"])  # type: ignore[index]
            for value in model_results.values()
        )
        results.append({
            "assignment_id": target.assignment_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "solver_id": target.solver_id,
            "condition_id": target.condition_id,
            "rubric_policy": target.rubric_policy.value,
            "pairwise_preference_scores": {
                "status": "same_artifact" if same_artifact else "completed",
                "initial_submission_id": target.submission_ids[0],
                "final_submission_id": target.submission_ids[-1],
                "order": None if same_artifact else order,
                "model_results": model_results,
                "panel_mean": panel_mean,
                "interpretation": (
                    "1 favors the final artifact. 0 favors the initial artifact. "
                    "A tie or identical artifacts score 0.5."
                ),
            },
        })
    return results
