"""Task-level resampling for revision evaluation effects."""

from __future__ import annotations

from functools import lru_cache

import numpy as np


BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 0


def task_bootstrap_interval(values: list[float]) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    array = np.asarray(values, dtype=np.float64)
    estimates = array[_bootstrap_indices(len(values))].mean(axis=1)
    lower, upper = np.quantile(estimates, (0.025, 0.975))
    return float(lower), float(upper)


@lru_cache(maxsize=None)
def _bootstrap_indices(task_count: int) -> np.ndarray:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    return rng.integers(
        0,
        task_count,
        size=(BOOTSTRAP_SAMPLES, task_count),
    )
