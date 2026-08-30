"""Checkpoint-wide scoring checks for one active rubric generation."""

from __future__ import annotations

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    preflight_full_rubric_generation,
)
from rubric_gen.submission_revision.judging.models import (
    GradingEngine,
    grading_engine_for_benchmark,
)
from rubric_gen.submission_revision.rubric_generation import RubricGeneration


def validate_generation_scoring_structure(
    generation: RubricGeneration,
    *,
    benchmark: SubmissionBenchmarkId,
) -> dict[str, object]:
    """Validate artifact-independent engine limits for an active rubric.

    Empty fixed evidence isolates rubric parsing, criterion counts, call counts,
    schema size, and rubric-only request size. The exact future artifact remains
    unknown and receives a separate checkpoint-wide preflight before dispatch.
    """

    if not isinstance(generation, RubricGeneration):
        raise ValueError("generation must be a RubricGeneration")
    if not isinstance(benchmark, SubmissionBenchmarkId):
        raise ValueError("benchmark must be a SubmissionBenchmarkId")
    engine = grading_engine_for_benchmark(benchmark)
    if engine is not GradingEngine.FULL_RUBRIC_STRUCTURED:
        raise ValueError(f"unsupported rubric grading engine: {engine.value}")
    cost_shape = preflight_full_rubric_generation(
        generation.rubric.content,
        review_text="",
        answer_text="",
    )
    return {
        "benchmark": benchmark.value,
        "grading_engine": engine.value,
        "generation_sha256": generation.generation_sha256,
        "rubric_sha256": generation.rubric.content_sha256,
        "scope": "rubric-structure-and-empty-evidence-request-shape",
        "cost_shape": cost_shape,
    }


def preflight_generation_dispatch(
    generation: RubricGeneration,
    *,
    benchmark: SubmissionBenchmarkId,
    review_text: str,
    answer_text: str,
) -> dict[str, object]:
    """Validate the active rubric before dispatch and return its exact binding."""

    if not isinstance(generation, RubricGeneration):
        raise ValueError("generation must be a RubricGeneration")
    if type(review_text) is not str or type(answer_text) is not str:
        raise ValueError("judge inputs must be strings")
    engine = grading_engine_for_benchmark(benchmark)
    if engine is not GradingEngine.FULL_RUBRIC_STRUCTURED:
        raise ValueError(f"unsupported rubric grading engine: {engine.value}")
    cost_shape = preflight_full_rubric_generation(
        generation.rubric.content,
        review_text=review_text,
        answer_text=answer_text,
    )
    return {
        "grading_engine": engine.value,
        "generation_sha256": generation.generation_sha256,
        "rubric_sha256": generation.rubric.content_sha256,
        "review_text_sha256": sha256_text(review_text),
        "answer_text_sha256": sha256_text(answer_text),
        "cost_shape": cost_shape,
    }
