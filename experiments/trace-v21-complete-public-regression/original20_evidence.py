"""Shared identities and read-only sources for Original20 heldout reanalysis."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

from rubric_gen.submission_revision.experiment import Experiment

from run_neutral_heldout5 import neutral_scope, source_targets


ROOT = Path(__file__).resolve().parents[2]
RESULT40_BUNDLE = (
    ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
)
if str(RESULT40_BUNDLE) not in sys.path:
    sys.path.insert(0, str(RESULT40_BUNDLE))

from audit_scope import completed_historical_experiment  # noqa: E402


TASKS = (
    "da-10-1", "da-10-3", "da-12-2", "da-12-4", "da-13-1",
    "da-13-3", "da-13-5", "da-13-6", "da-14-1", "da-14-3",
    "da-14-8", "da-15-1", "da-15-2", "da-15-7", "da-15-8",
    "da-16-1", "da-18-5", "da-18-7", "da-19-1", "da-19-6",
)
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/"
    "evidence-calibrated-original20-v2"
)
NEUTRAL_POOL = RUN / "paraphrases"
EVIDENCE_ROOT = RUN / "evidence"


def case_plan(task_id: str, replicate: int) -> tuple[tuple[str, str], ...]:
    if task_id not in TASKS:
        raise ValueError(f"task is outside Original20: {task_id}")
    if replicate not in (1, 2, 3):
        raise ValueError(f"invalid Original20 replicate: {replicate}")
    return (
        ("static", "Full"),
        ("static", "User"),
        ("trace", "Full"),
        ("trace", "User"),
    )


@lru_cache(maxsize=1)
def experiments() -> dict[str, Experiment]:
    result = {
        "static_full": completed_historical_experiment("static-full"),
        "static_user": completed_historical_experiment("static-user"),
        "trace": completed_historical_experiment("current"),
    }
    if tuple(result["trace"].task_ids) != TASKS:
        raise RuntimeError("Original20 task membership changed")
    if any(tuple(experiment.task_ids) != TASKS for experiment in result.values()):
        raise RuntimeError("Original20 source task membership differs")
    return result


@lru_cache(maxsize=1)
def targets():
    return {
        name: source_targets(experiment)
        for name, experiment in experiments().items()
    }


def target_for(task_id: str, role: str, arm: str, replicate: int):
    case_plan(task_id, replicate)
    source_name = (
        "trace"
        if role == "trace"
        else "static_user"
        if arm == "User"
        else "static_full"
    )
    matches = [
        target
        for target in targets()[source_name]
        if target.task_id == task_id
        and target.replicate == replicate
        and (
            (arm == "User" and target.condition_id.startswith("user-"))
            or (arm == "Full" and not target.condition_id.startswith("user-"))
        )
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one Original20 target: {task_id} {role} {arm} rep {replicate}"
        )
    return matches[0]


def neutral_experiment() -> Experiment:
    return neutral_scope(experiments()["trace"], output_dir=NEUTRAL_POOL)
