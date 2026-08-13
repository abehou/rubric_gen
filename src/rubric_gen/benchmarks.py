"""Benchmark identities shared by experiment and agent workflows."""

from __future__ import annotations

from enum import StrEnum


class Benchmark(StrEnum):
    """Benchmarks supported by the randomized revision workflow."""

    BIOMNIBENCH_DA = "biomnibench-da"
    PAPERBENCH_CODE_DEV = "paperbench-code-dev"

