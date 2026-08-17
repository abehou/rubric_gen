"""Explicit registry for submission-revision benchmarks."""

from __future__ import annotations

from rubric_gen.benchmarks.base import SubmissionBenchmark, SubmissionBenchmarkId
from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.benchmarks.paperbench_code_dev.contract import PAPERBENCH_CODE_DEV


_SUBMISSION_BENCHMARKS: dict[SubmissionBenchmarkId, SubmissionBenchmark] = {
    SubmissionBenchmarkId.BIOMNIBENCH_DA: BIOMNIBENCH_DA,
    SubmissionBenchmarkId.PAPERBENCH_CODE_DEV: PAPERBENCH_CODE_DEV,
}


def get_submission_benchmark(
    benchmark: SubmissionBenchmarkId | str,
) -> SubmissionBenchmark:
    """Return the native contract for one submission benchmark."""

    return _SUBMISSION_BENCHMARKS[SubmissionBenchmarkId(benchmark)]
