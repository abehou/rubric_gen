"""Submission-benchmark contracts and registry access."""

from rubric_gen.benchmarks.base import (
    FinalEvidence,
    SubmissionBenchmark,
    SubmissionBenchmarkId,
)
from rubric_gen.benchmarks.registry import get_submission_benchmark

__all__ = [
    "FinalEvidence",
    "SubmissionBenchmark",
    "SubmissionBenchmarkId",
    "get_submission_benchmark",
]
