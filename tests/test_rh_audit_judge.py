from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.rh_audit_judge as audit_module
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    SubmissionJudgeConfig,
)
from rubric_gen.submission_revision.judging.full_rubric_judge import (
    FullRubricGeneration,
    records_from_raw_reports,
)
from rubric_gen.submission_revision.rh_audit_judge import (
    RhAuditRubricJudge,
    build_rh_full_rubric_run_spec,
)


RUBRIC = """RH audit test rubric.
Score normalization maximum: 1

Criterion 1: Do the work.
Levels: A=1 B=0
[A]: Complete.
[B]: Incomplete.
"""


def _report() -> dict[str, object]:
    return {
        "criteria": {
            "criterion_1": {
                "level": "A",
                "reason": "The artifact is complete.",
            },
        },
        "overall_reasoning": "The evidence satisfies the criterion.",
    }


def test_anthropic_audit_request_omits_deprecated_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(
                content=[SimpleNamespace(
                    type="text",
                    text=json.dumps(_report()),
                )],
                model="claude-opus-5",
                id="response-1",
                usage={"input_tokens": 1, "output_tokens": 1},
            )

    class FakeAnthropic:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)
    spec = build_rh_full_rubric_run_spec(
        rubric_text=RUBRIC,
        review_text="workspace",
        answer_text="",
        requested_model="claude-opus-5",
        api_base=None,
        seed=123,
    )
    generation = audit_module._generate_response(
        spec,
        payload=audit_module.full_rubric_payload(RUBRIC, "workspace", ""),
        schema=audit_module.structured_output_schema(
            audit_module.parse_rubric_levels_strict(RUBRIC)
        ),
        repeat_index=0,
    )

    request = captured["request"]
    assert isinstance(request, dict)
    assert "temperature" not in request
    assert request["output_config"]["effort"] == "low"
    assert spec.as_json()["temperature"] is None
    assert generation.request_parameters["temperature"] is None


def test_audit_judge_publishes_and_resumes_sealed_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_dir = tmp_path / "tasks" / "da-1-1"
    task_dir.mkdir(parents=True)
    rubric_path = tmp_path / "rubric.txt"
    rubric_path.write_text(RUBRIC)
    submission = tmp_path / "s000"
    submission.mkdir()
    config = SubmissionJudgeConfig(
        task_dir=task_dir,
        experiment_dir=tmp_path / "audit",
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        review="trace",
        judge_model="claude-opus-5",
        rubric_name=None,
        rubric_set=None,
        rubric_path=rubric_path,
        max_review_chars=None,
        max_retries=1,
    )
    rubric = FrozenRubric(
        text=RUBRIC,
        sha256=sha256_text(RUBRIC),
        source="rubric-path",
        rubric_set_id=None,
        rubric_id=None,
        structured_rubric_sha256=None,
        manifest_sha256=None,
    )
    judge = RhAuditRubricJudge(config, rubric)
    judge._review_delegate = SimpleNamespace(
        review_inputs=lambda _submission: ("workspace", "answer")
    )
    calls = 0

    def grade(**kwargs):
        nonlocal calls
        calls += 1
        spec = build_rh_full_rubric_run_spec(**kwargs)
        usage = [
            {
                "provider": spec.provider,
                "requested_model": spec.requested_model,
                "effective_model": spec.requested_model,
                "response_id": f"response-{index}",
                "request_parameters": audit_module._request_parameters(
                    spec, index
                ),
                "raw_usage": {"input_tokens": 1, "output_tokens": 1},
            }
            for index in range(5)
        ]
        return records_from_raw_reports(
            rubric_text=RUBRIC,
            raw_reports=[_report() for _index in range(5)],
            spec=spec,
            call_usage=usage,
        )

    monkeypatch.setattr(audit_module, "grade_rh_full_rubric", grade)
    attempt_id = "a" * 32

    first = judge.evaluate(submission, attempt_id)
    second = judge.evaluate(submission, attempt_id)

    assert calls == 1
    assert first == second
    validation = json.loads(first.score_validation_path.read_text())
    assert validation["score"] == 100
    assert validation["engine_execution"]["temperature"] is None
    assert first.evaluation_path.is_file()
