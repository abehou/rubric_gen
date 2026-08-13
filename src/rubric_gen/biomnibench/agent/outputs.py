"""Benchmark-specific solver output contracts."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from rubric_gen.benchmarks import Benchmark


def solver_required_outputs(benchmark: Benchmark | str) -> tuple[str, ...]:
    """Return the top-level outputs required from one solver workspace."""

    if Benchmark(benchmark) is Benchmark.PAPERBENCH_CODE_DEV:
        return ("submission",)
    return ("trace.md", "answer.txt")


def solver_output_errors(
    workspace: Path,
    benchmark: Benchmark | str,
) -> list[str]:
    """Validate the native deliverables for one benchmark."""

    if Benchmark(benchmark) is Benchmark.PAPERBENCH_CODE_DEV:
        submission = workspace / "submission"
        try:
            submission_stat = os.lstat(submission)
        except OSError:
            return ["missing_or_invalid: submission"]
        if not stat.S_ISDIR(submission_stat.st_mode):
            return ["missing_or_invalid: submission"]
        readme = submission / "README.md"
        try:
            readme_stat = os.lstat(readme)
        except OSError:
            return ["missing_or_invalid: submission/README.md"]
        if not stat.S_ISREG(readme_stat.st_mode) or readme_stat.st_size == 0:
            return ["missing_or_invalid: submission/README.md"]
        return []

    errors: list[str] = []
    for name in solver_required_outputs(benchmark):
        path = workspace / name
        try:
            path_stat = os.lstat(path)
        except OSError:
            errors.append(f"missing_or_invalid: {name}")
            continue
        if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_size == 0:
            errors.append(f"missing_or_invalid: {name}")
    return errors
