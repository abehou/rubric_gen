from __future__ import annotations

import pytest

from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.judging.preflight import (
    JudgeDispatchInput,
    preflight_judge_dispatches,
)


AUTORUBRIC = """RUBRIC: Test

Criterion 1: Quality
Levels: A=100 B=0
[A]: Complete.
[B]: Missing.
"""

PAPERBENCH = """PaperBench Code-Dev rubric.
Score normalization maximum: 1

Criterion 1: Implementation
Levels: A=1 B=0
[A]: Complete.
[B]: Missing.
"""


def test_biomni_stage_preflight_uses_one_call_per_job() -> None:
    stage = preflight_judge_dispatches(
        SubmissionBenchmarkId.BIOMNIBENCH_DA,
        iter((
            JudgeDispatchInput(AUTORUBRIC, "short", ""),
            JudgeDispatchInput(AUTORUBRIC, "longer evidence", "answer"),
        )),
    )

    assert stage["grading_engine"] == "full-rubric-structured"
    assert stage["dispatch_count"] == 2
    assert stage["calls"] == 2
    assert stage["request_bytes"] == sum(
        shape["total_request_content_bytes"] for shape in stage["jobs"]
    )
    assert stage["output_tokens"] == sum(
        shape["total_output_tokens"] for shape in stage["jobs"]
    )


def test_paperbench_stage_preflight_uses_one_call_per_job() -> None:
    stage = preflight_judge_dispatches(
        SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
        (
            JudgeDispatchInput(PAPERBENCH, "first workspace", ""),
            JudgeDispatchInput(PAPERBENCH, "second workspace", "answer"),
        ),
    )

    assert stage["grading_engine"] == "full-rubric-structured"
    assert stage["dispatch_count"] == 2
    assert stage["calls"] == 2
    assert stage["request_bytes"] == sum(
        shape["total_request_content_bytes"] for shape in stage["jobs"]
    )
    assert all(shape["schema_bytes"] > 0 for shape in stage["jobs"])


def test_stage_preflight_validates_every_job_before_any_dispatch() -> None:
    invalid = PAPERBENCH.replace("Levels: A=1 B=0", "Levels: A=1 A=0")

    with pytest.raises(ValueError):
        preflight_judge_dispatches(
            SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
            (
                JudgeDispatchInput(PAPERBENCH, "valid", ""),
                JudgeDispatchInput(invalid, "invalid", ""),
            ),
        )


def test_stage_preflight_rejects_an_empty_iterable() -> None:
    with pytest.raises(
        ValueError,
        match="judge dispatch stage must contain at least one job",
    ):
        preflight_judge_dispatches(
            SubmissionBenchmarkId.BIOMNIBENCH_DA,
            iter(()),
        )
