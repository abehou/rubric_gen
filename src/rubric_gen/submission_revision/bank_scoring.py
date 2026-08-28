"""Boundary-wide scoring checks for one complete rubric bank."""

from __future__ import annotations

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    preflight_full_rubric_bank,
)
from rubric_gen.submission_revision.judging.models import (
    GradingEngine,
    grading_engine_for_benchmark,
)
from rubric_gen.submission_revision.rubric_bank import RubricBank


def validate_bank_scoring_structure(
    bank: RubricBank,
    *,
    benchmark: SubmissionBenchmarkId,
) -> dict[str, object]:
    """Validate artifact-independent engine limits for a proposed bank.

    Empty fixed evidence isolates rubric parsing, criterion counts, call counts,
    schema size, and rubric-only request size. The exact future artifact remains
    unknown and receives a separate boundary-wide preflight before dispatch.
    """

    if not isinstance(bank, RubricBank):
        raise ValueError("bank must be a RubricBank")
    if not isinstance(benchmark, SubmissionBenchmarkId):
        raise ValueError("benchmark must be a SubmissionBenchmarkId")
    engine = grading_engine_for_benchmark(benchmark)
    rubric_texts = [item.rubric.content for item in bank.items]
    if engine is not GradingEngine.FULL_RUBRIC_STRUCTURED:
        raise ValueError(f"unsupported rubric-bank grading engine: {engine.value}")
    cost_shape = preflight_full_rubric_bank(
        rubric_texts,
        review_text="",
        answer_text="",
    )
    return {
        "benchmark": benchmark.value,
        "grading_engine": engine.value,
        "bank_sha256": bank.content_sha256,
        "member_sha256s": [
            item.rubric.content_sha256 for item in bank.items
        ],
        "scope": "rubric-structure-and-empty-evidence-request-shape",
        "cost_shape": cost_shape,
    }


def preflight_bank_dispatch(
    bank: RubricBank,
    *,
    benchmark: SubmissionBenchmarkId,
    review_text: str,
    answer_text: str,
) -> dict[str, object]:
    """Validate the whole bank before dispatch and return its exact binding."""

    if not isinstance(bank, RubricBank):
        raise ValueError("bank must be a RubricBank")
    if type(review_text) is not str or type(answer_text) is not str:
        raise ValueError("judge inputs must be strings")
    engine = grading_engine_for_benchmark(benchmark)
    member_hashes = [item.rubric.content_sha256 for item in bank.items]
    if engine is not GradingEngine.FULL_RUBRIC_STRUCTURED:
        raise ValueError(f"unsupported rubric-bank grading engine: {engine.value}")
    cost_shape = preflight_full_rubric_bank(
        [item.rubric.content for item in bank.items],
        review_text=review_text,
        answer_text=answer_text,
    )
    return {
        "grading_engine": engine.value,
        "bank_sha256": bank.content_sha256,
        "member_sha256s": member_hashes,
        "review_text_sha256": sha256_text(review_text),
        "answer_text_sha256": sha256_text(answer_text),
        "cost_shape": cost_shape,
    }
