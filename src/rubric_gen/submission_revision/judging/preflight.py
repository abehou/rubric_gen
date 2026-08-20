"""Pure whole-stage cost-shape validation for fixed grading engines."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rubric_gen.benchmarks import SubmissionBenchmarkId
from .models import GradingEngine, grading_engine_for_benchmark
from .full_rubric_judge import full_rubric_cost_shape


@dataclass(frozen=True)
class JudgeDispatchInput:
    """The exact rubric and evidence for one planned engine dispatch."""

    rubric_text: str
    review_text: str
    answer_text: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not str
            for value in (self.rubric_text, self.review_text, self.answer_text)
        ):
            raise TypeError("judge dispatch inputs must be text")


def preflight_judge_dispatches(
    benchmark: SubmissionBenchmarkId | str,
    dispatches: Iterable[JudgeDispatchInput],
) -> dict[str, object]:
    """Validate every planned dispatch before returning whole-stage totals.

    This function has no provider or filesystem access. It consumes dispatches
    one at a time and retains only their cost shapes. The caller must invoke it
    before it submits the first deduplicated job. The returned totals are
    resource measurements, not a monetary cost estimate.
    """

    if isinstance(dispatches, (str, bytes, bytearray)):
        raise TypeError("judge dispatch stage must be an iterable of jobs")

    resolved_benchmark = SubmissionBenchmarkId(benchmark)
    engine = grading_engine_for_benchmark(resolved_benchmark)
    shapes: list[dict[str, int]] = []
    calls = 0
    request_bytes = 0
    output_tokens = 0
    largest_request_bytes_per_call = 0

    for dispatch in dispatches:
        if not isinstance(dispatch, JudgeDispatchInput):
            raise TypeError("judge dispatch stage contains an invalid job")
        if engine is not GradingEngine.FULL_RUBRIC_STRUCTURED:
            raise ValueError(f"unsupported grading engine: {engine.value}")
        shape = full_rubric_cost_shape(
            dispatch.rubric_text,
            review_text=dispatch.review_text,
            answer_text=dispatch.answer_text,
        )
        shape_json = shape.as_json()
        calls += shape.calls
        request_bytes += shape.total_request_content_bytes
        output_tokens += shape.total_output_tokens
        largest_request_bytes_per_call = max(
            largest_request_bytes_per_call,
            shape.request_content_bytes_per_call,
        )
        request_byte_measurement = (
            "system-plus-canonical-json-payload-plus-canonical-schema"
        )
        shapes.append(shape_json)

    if not shapes:
        raise ValueError("judge dispatch stage must contain at least one job")

    return {
        "benchmark": resolved_benchmark.value,
        "grading_engine": engine.value,
        "dispatch_count": len(shapes),
        "calls": calls,
        "request_byte_measurement": request_byte_measurement,
        "largest_request_bytes_per_call": largest_request_bytes_per_call,
        "request_bytes": request_bytes,
        "output_tokens": output_tokens,
        "jobs": shapes,
    }
