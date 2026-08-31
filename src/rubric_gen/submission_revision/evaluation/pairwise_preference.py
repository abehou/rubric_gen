"""Build and summarize pairwise preference scores."""

from __future__ import annotations

from statistics import fmean

from rubric_gen.submission_revision.evaluation.jobs import (
    ORDERINGS,
    EvaluationTarget,
    PairwisePreferenceJob,
    _submission_content_sha256,
)


def assignment_reference(
    job: PairwisePreferenceJob,
    judgment: dict[str, object],
) -> dict[str, object]:
    pair = job.pair
    return {
        "assignment_id": job.target.assignment_id,
        "task_id": job.target.task_id,
        "replicate": job.target.replicate,
        "condition_id": job.target.condition_id,
        "model": job.model,
        "ordering": job.ordering,
        "rubric_score_source": "in-loop-original-rubric-score",
        "higher_submission_id": pair.higher_submission_id,
        "lower_submission_id": pair.lower_submission_id,
        "higher_rubric_score": pair.higher_score,
        "lower_rubric_score": pair.lower_score,
        "rubric_score_gap": pair.score_gap,
        "higher_content_sha256": _submission_content_sha256(
            pair.higher_submission
        ),
        "lower_content_sha256": _submission_content_sha256(
            pair.lower_submission
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


def _higher_score_preference_value(ordering: str, preferred: object) -> float:
    if preferred == "tie":
        return 0.5
    higher_response = "response_A" if ordering == "higher-first" else "response_B"
    return 1.0 if preferred == higher_response else 0.0


def summarize(
    targets: tuple[EvaluationTarget, ...],
    records: list[dict[str, object]],
    models: tuple[str, ...],
) -> list[dict[str, object]]:
    records_by_key = {
        (
            str(record["assignment_id"]),
            str(record["model"]),
            str(record["ordering"]),
        ): record
        for record in records
    }
    results: list[dict[str, object]] = []
    for target in targets:
        ordered_pair = (
            target.rubric_ordered_pair()
            if len(target.submission_ids) >= 2
            else None
        )
        model_preferences: dict[str, object] = {}
        for model in models:
            if ordered_pair is None:
                model_preferences[model] = {
                    "status": "skipped",
                    "reason": "initial and final are the same artifact",
                    "higher_score_preference_rate": 0.5,
                }
                continue
            order_values: dict[str, float] = {}
            order_decisions: dict[str, str] = {}
            for ordering in ORDERINGS:
                record = records_by_key[
                    (target.assignment_id, model, ordering)
                ]
                verdict = record["verdict"]
                assert isinstance(verdict, dict)
                preferred = verdict["preferred_response"]
                assert isinstance(preferred, str)
                order_decisions[ordering] = preferred
                order_values[ordering] = _higher_score_preference_value(
                    ordering,
                    preferred,
                )
            model_preferences[model] = {
                "status": "completed",
                "order_decisions": order_decisions,
                "order_higher_score_preference_values": order_values,
                "higher_score_preference_rate": fmean(order_values.values()),
            }
        raw_pairwise_mean = fmean(
            float(value["higher_score_preference_rate"])  # type: ignore[index]
            for value in model_preferences.values()
        )
        score_gap = ordered_pair.score_gap if ordered_pair is not None else 0.0
        order_agreement = raw_pairwise_mean if score_gap > 0 else 0.5
        higher_id = (
            ordered_pair.higher_submission_id
            if ordered_pair is not None
            else target.submission_ids[0]
        )
        lower_id = (
            ordered_pair.lower_submission_id
            if ordered_pair is not None
            else target.submission_ids[0]
        )
        higher_score = (
            ordered_pair.higher_score
            if ordered_pair is not None
            else target.fixed_original_scores[0]
        )
        lower_score = (
            ordered_pair.lower_score
            if ordered_pair is not None
            else target.fixed_original_scores[0]
        )
        results.append({
            "assignment_id": target.assignment_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "condition_id": target.condition_id,
            "rubric_policy": target.rubric_policy.value,
            "pairwise_preference_scores": {
                "rubric_score_source": "in-loop-original-rubric-score",
                "status": "completed" if ordered_pair is not None else "skipped",
                "skip_reason": (
                    None
                    if ordered_pair is not None
                    else "initial and final are the same artifact"
                ),
                "higher_submission_id": higher_id,
                "lower_submission_id": lower_id,
                "higher_rubric_score": higher_score,
                "lower_rubric_score": lower_score,
                "rubric_score_gap": score_gap,
                "strict_rubric_order": score_gap > 0,
                "model_results": model_preferences,
                "panel_mean_higher_score_preference_rate": raw_pairwise_mean,
                "rubric_order_agreement": order_agreement,
                "interpretation": (
                    "1 favors the artifact with the higher original-rubric score. "
                    "0 favors the lower-scoring artifact. A zero score gap is "
                    "uninformative and contributes neutral agreement of 0.5."
                ),
            },
        })
    return results
