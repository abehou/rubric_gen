"""Native aggregation of externally supplied judgments, without model calls.

These are not the project's clipped W/S/H scores. Matching arithmetic does not
make a different judge or multi-round protocol an official benchmark run.
"""
import math


def healthbench_task_score(points: list[int], met: list[bool]) -> float:
    if not points or len(points) != len(met):
        raise ValueError("one judgment is required for every criterion")
    if any(type(p) is not int or p == 0 for p in points) or any(type(m) is not bool for m in met):
        raise ValueError("expected nonzero integer points and boolean judgments")
    maximum = sum(p for p in points if p > 0)
    if not maximum:
        raise ValueError("positive criterion points are required")
    return sum(p for p, m in zip(points, met, strict=True) if m) / maximum


def healthbench_mean(scores: list[float]) -> float:
    if not scores or not all(math.isfinite(s) for s in scores):
        raise ValueError("finite task scores are required")
    return max(0.0, min(1.0, math.fsum(scores) / len(scores)))


def researchqa_coverage(labels: list[str]) -> float:
    values = {"Not at all": 0, "Barely": 1, "Moderately": 2, "Mostly": 3, "Completely": 4}
    if not labels or any(label not in values for label in labels):
        raise ValueError("one valid coverage label is required per criterion")
    return sum(values[label] for label in labels) / (4 * len(labels))
