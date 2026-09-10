"""Isolated criterion application calls and deterministic response aggregation."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass

from rubric_gen.submission_revision.evolution_protocol import (
    CriterionCandidate, validated_validation_response, validation_schema,
)
from rubric_gen.submission_revision.evolution_serialization import canonical_json


@dataclass(frozen=True)
class ValidationStageResult:
    raw_text: str
    value: object
    attempt_count: int
    fallback_reason: str | None = None
    calls: tuple[dict[str, object], ...] = ()


def validate_independently(
    *,
    stage: Callable[..., ValidationStageResult],
    candidates: tuple[CriterionCandidate, ...],
    artifact_ids: tuple[str, ...],
    evidence: str,
    fallback_text: str,
) -> ValidationStageResult:
    """Keep other artifacts out of each application judgment's context."""
    payload = json.loads(evidence)
    artifacts = {item["artifact_id"]: item for item in payload["artifacts"]}
    if set(artifacts) != set(artifact_ids):
        raise ValueError("validation evidence artifact coverage differs")
    fallback = json.loads(fallback_text)
    def validate_one(artifact_id: str) -> ValidationStageResult:
        one_fallback = json.loads(fallback_text)
        for item in one_fallback["validations"]:
            item["artifact_applications"] = [
                application for application in item["artifact_applications"]
                if application["artifact_id"] == artifact_id
            ]
        return stage(
            stage="validation",
            evidence=canonical_json({**payload, "artifacts": [artifacts[artifact_id]]}),
            response_schema=validation_schema(candidates, (artifact_id,)),
            validator=lambda text, aid=artifact_id: validated_validation_response(
                text, candidates=candidates, artifact_ids=(aid,),
            ),
            fallback_text=canonical_json(one_fallback),
        )

    # Independent blinded inputs; preserve artifact order when combining results.
    # Each production provider call still acquires the shared global reservation.
    # Bound local fan-out so many simultaneous studies cannot create unbounded
    # worker threads; this is not an additional provider-capacity pool.
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rubric-validation")
    futures = []
    try:
        futures = [executor.submit(validate_one, aid) for aid in artifact_ids]
        parts = [future.result() for future in futures]
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    return combine_validation_results(
        candidates=candidates, artifact_ids=artifact_ids,
        parts=parts, fallback_text=fallback_text,
    )

def combine_validation_results(
    *, candidates: tuple[CriterionCandidate, ...],
    artifact_ids: tuple[str, ...], parts: list[ValidationStageResult], fallback_text: str,
) -> ValidationStageResult:
    calls = tuple({
        "artifact_id": aid, "raw_text": part.raw_text,
        "attempt_count": part.attempt_count, "fallback_reason": part.fallback_reason,
    } for aid, part in zip(artifact_ids, parts, strict=True))
    fallback = json.loads(fallback_text)
    attempts = sum(part.attempt_count for part in parts)
    failures = [part.fallback_reason for part in parts if part.fallback_reason]
    if failures:
        # A partly validated candidate must never be admitted.
        return ValidationStageResult(
            fallback_text,
            validated_validation_response(fallback_text, candidates=candidates,
                                          artifact_ids=artifact_ids),
            attempts, " ".join(failures), calls,
        )
    records = [json.loads(part.raw_text)["validations"] for part in parts]
    for index, item in enumerate(fallback["validations"]):
        judgments = [part[index] for part in records]
        item["observable"] = all(j["observable"] for j in judgments)
        item["nonredundant"] = all(j["nonredundant"] for j in judgments)
        item["artifact_applications"] = [
            j["artifact_applications"][0] for j in judgments
        ]
        item["reason"] = " ".join(dict.fromkeys(j["reason"] for j in judgments))
    text = canonical_json(fallback)
    return ValidationStageResult(
        text, validated_validation_response(text, candidates=candidates,
                                            artifact_ids=artifact_ids), attempts, calls=calls,
    )
