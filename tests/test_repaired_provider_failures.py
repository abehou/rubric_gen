from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.evaluation.rubric_judge as rubric_judge_module
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.detection.job_runner import DetectionJobRunner, _JobPaths
from rubric_gen.runtime.failures import (
    REPAIRED_PROVIDER_FAILURES_ENV,
    retry_repaired_provider_failure,
)
from rubric_gen.runtime.llm import GenerationResult, StructuredRequest
from rubric_gen.submission_revision.evaluation.score_execution import (
    RubricFreeScoreStage,
)
from rubric_gen.submission_revision.evaluation.rubric_judge import RubricScoreJudge
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    SubmissionJudgeConfig,
)


RUBRIC = """Recovery test rubric.
Score normalization maximum: 1

Criterion 1: Do the work.
Levels: A=1 B=0
[A]: Complete.
[B]: Incomplete.
"""


def _request() -> StructuredRequest:
    return StructuredRequest(
        instructions="instructions",
        evidence="evidence",
        schema_name="recovery",
        schema={"type": "object", "additionalProperties": False},
    )


def _generation(model: str, text: str) -> GenerationResult:
    return GenerationResult(
        text=text,
        provider="openai",
        requested_model=model,
        effective_model=model,
        response_id="response-recovered",
        request_parameters={},
    )


def test_repaired_provider_failure_opt_in_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert retry_repaired_provider_failure("billing") is False
    monkeypatch.setenv(REPAIRED_PROVIDER_FAILURES_ENV, "billing")
    assert retry_repaired_provider_failure("billing") is True
    assert retry_repaired_provider_failure("authentication") is False
    monkeypatch.setenv(REPAIRED_PROVIDER_FAILURES_ENV, "structural")
    with pytest.raises(RuntimeError, match="must name a comma-separated subset"):
        retry_repaired_provider_failure("structural")


def test_rubric_free_recovery_preserves_billing_attempt_and_uses_next_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "gpt-5.6-sol"
    request = _request()
    identity = {"job": "absolute"}
    calls = 0

    def generate(requested_model: str, _request: StructuredRequest) -> GenerationResult:
        nonlocal calls
        calls += 1
        return _generation(
            requested_model,
            '{"score":10,"explanation":"recovered"}',
        )

    stage = RubricFreeScoreStage(
        SimpleNamespace(output_dir=tmp_path),
        (),
        generation_operation=generate,
    )
    stage._assert_current_dispatch = lambda **_kwargs: None
    attempt_root = tmp_path / "absolute_score" / "attempts" / "key"
    attempt_root.mkdir(parents=True)
    first_path = attempt_root / "attempt-001.json"
    first = {
        "identity": identity,
        "attempt": 1,
        "remote_completion": "unknown",
        "category": "billing",
        "error": "credits exhausted",
    }
    first_path.write_text(json.dumps(first))

    with pytest.raises(RuntimeError, match="recorded billing"):
        stage._run_structured_judgment(
            model=model,
            request=request,
            key="key",
            instrument="absolute",
            identity=identity,
            validator=lambda value: None,
        )
    assert calls == 0

    monkeypatch.setenv(REPAIRED_PROVIDER_FAILURES_ENV, "billing")
    record = stage._run_structured_judgment(
        model=model,
        request=request,
        key="key",
        instrument="absolute",
        identity=identity,
        validator=lambda value: None,
    )
    assert calls == 1
    assert record["attempt_count"] == 2
    assert json.loads(first_path.read_text()) == first
    assert (attempt_root / "attempt-002.json").is_file()


def test_direct_recovery_preserves_billing_attempt_and_uses_next_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "gpt-5.6-sol"
    request = _request()
    calls = 0

    def generate(requested_model: str, _request: StructuredRequest) -> GenerationResult:
        nonlocal calls
        calls += 1
        return _generation(
            requested_model,
            '{"reason":"recovered","score":0}',
        )

    runner = DetectionJobRunner(
        SimpleNamespace(detection="rh"),
        {},
        generate,
        lambda _model, _request: 1,
        lambda _case: pytest.fail("payload should not be loaded"),
    )
    root = tmp_path / "case"
    request_root = root / "chunk-001"
    request_root.mkdir(parents=True)
    first_path = request_root / "attempt-001.json"
    first = {
        "identity": {"model": model, "request": asdict(request)},
        "attempt": 1,
        "remote_completion": "unknown",
        "category": "billing",
        "error": "credits exhausted",
    }
    first_path.write_text(json.dumps(first))
    runner._local.paths = _JobPaths(root=root, score=root / "score.json")
    runner._local.request = ("chunk", 1)
    runner._local.attempts = 1
    runner._local.publication_only = False

    with pytest.raises(RuntimeError, match="recorded billing"):
        runner._saved_or_generate(model, request)
    assert calls == 0

    monkeypatch.setenv(REPAIRED_PROVIDER_FAILURES_ENV, "billing")
    recovered = runner._saved_or_generate(model, request)
    assert calls == 1
    assert recovered.response_id == "response-recovered"
    assert json.loads(first_path.read_text()) == first
    assert (request_root / "attempt-002.json").is_file()


def test_full_rubric_recovery_preserves_billing_attempt_and_uses_next_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_dir = tmp_path / "tasks" / "task"
    task_dir.mkdir(parents=True)
    rubric_path = tmp_path / "rubric.txt"
    rubric_path.write_text(RUBRIC)
    submission = tmp_path / "submission"
    submission.mkdir()
    rubric = FrozenRubric(
        text=RUBRIC,
        sha256=sha256_text(RUBRIC),
        source="rubric-path",
        rubric_set_id=None,
        rubric_id=None,
        structured_rubric_sha256=None,
        manifest_sha256=None,
    )
    judge = RubricScoreJudge(
        SubmissionJudgeConfig(
            task_dir=task_dir,
            experiment_dir=tmp_path / "audit",
            benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
            review="trace",
            judge_model="gpt-5.6-sol",
            rubric_name=None,
            rubric_set=None,
            rubric_path=rubric_path,
            max_review_chars=None,
        ),
        rubric,
    )
    judge._review_delegate = SimpleNamespace(
        review_inputs=lambda _submission: ("workspace", "answer")
    )
    attempt_id = "a" * 32
    root = judge._evaluation_root(submission, attempt_id)
    attempt_root = root.parent / f"{attempt_id}.attempts"
    attempt_root.mkdir(parents=True)
    identity = {
        "scoring_identity": judge.scoring_identity(),
        "review_input_sha256": sha256_text("workspace"),
        "answer_input_sha256": sha256_text("answer"),
    }
    first_path = attempt_root / "attempt-001.json"
    first = {
        "identity": identity,
        "attempt": 1,
        "remote_completion": "unknown",
        "failure_category": "billing",
        "error": "credits exhausted",
    }
    first_path.write_text(json.dumps(first))
    calls = 0

    def grade(**kwargs):
        nonlocal calls
        calls += 1
        spec = rubric_judge_module.build_rubric_score_run_spec(**kwargs)
        return rubric_judge_module.records_from_report(
            rubric_text=RUBRIC,
            raw_report={
                "criteria": {
                    "criterion_1": {
                        "level": "A",
                        "reason": "Complete.",
                    },
                },
                "overall_reasoning": "Complete.",
            },
            spec=spec,
            call_usage={
                "provider": spec.provider,
                "requested_model": spec.requested_model,
                "effective_model": spec.requested_model,
                "response_id": "response-recovered",
                "request_parameters": rubric_judge_module._request_parameters(spec),
                "raw_usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    monkeypatch.setattr(rubric_judge_module, "grade_rubric_score", grade)
    with pytest.raises(RuntimeError, match="requires repair"):
        judge.evaluate(submission, attempt_id)
    assert calls == 0

    monkeypatch.setenv(REPAIRED_PROVIDER_FAILURES_ENV, "billing")
    judge.evaluate(submission, attempt_id)
    assert calls == 1
    assert json.loads(first_path.read_text()) == first
    assert (attempt_root / "attempt-002.json").is_file()
