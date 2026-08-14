"""Benchmark identities and submission contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rubric_gen.benchmarks.contracts import SubmissionBenchmark


class Benchmark(StrEnum):
    """Benchmarks supported by the randomized revision workflow."""

    BIOMNIBENCH_DA = "biomnibench-da"
    PAPERBENCH_CODE_DEV = "paperbench-code-dev"


def get_benchmark(benchmark: Benchmark | str) -> "SubmissionBenchmark":
    """Return the complete native contract for one submission benchmark."""

    resolved = Benchmark(benchmark)
    if resolved is Benchmark.BIOMNIBENCH_DA:
        from rubric_gen.benchmarks.biomnibench_da import BIOMNIBENCH_DA

        return BIOMNIBENCH_DA
    from rubric_gen.benchmarks.paperbench_code_dev import PAPERBENCH_CODE_DEV

    return PAPERBENCH_CODE_DEV


__all__ = ["Benchmark", "get_benchmark"]
