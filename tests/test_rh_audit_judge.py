from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.rh_audit_judge as audit_module
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    SubmissionJudgeConfig,
)
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    FullRubricGeneration,
    FullRubricJudgeError,
    records_from_raw_reports,
)
from rubric_gen.submission_revision.rh_audit_judge import (
    RH_FULL_RUBRIC_ENGINE_IDENTITY,
    RH_FULL_RUBRIC_SYSTEM_PROMPT,
    RhAuditRubricJudge,
    build_rh_full_rubric_run_spec,
    grade_rh_full_rubric,
    parse_rh_structured_output,
    rh_full_rubric_cost_shape,
    rh_full_rubric_payload,
    rh_structured_output_schema,
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


def _wire_report() -> dict[str, object]:
    return {
        "criteria": [{
            "level_index": 0,
            "reason": "The artifact is complete.",
        }],
        "overall_reasoning": "The evidence satisfies the criterion.",
    }


def _records(**kwargs):
    spec = build_rh_full_rubric_run_spec(**kwargs)
    usage = [
        {
            "provider": spec.provider,
            "requested_model": spec.requested_model,
            "effective_model": spec.requested_model,
            "response_id": f"response-{index}",
            "request_parameters": audit_module._request_parameters(spec, index),
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


def _many_criterion_rubric(count: int) -> str:
    criteria = []
    for index in range(1, count + 1):
        criteria.append(
            f"Criterion {index}: Implement item {index}.\n"
            "Levels: A=1 B=0\n"
            "[A]: Complete and correct.\n"
            "[B]: Missing or incorrect.\n"
        )
    return (
        "RH audit test rubric.\n"
        f"Score normalization maximum: {count}\n\n"
        + "\n".join(criteria)
    )


def test_compact_schema_and_payload_keep_rubric_values_out_of_grammar() -> None:
    small_rubric = _many_criterion_rubric(2)
    large_rubric = _many_criterion_rubric(151)
    small = rh_full_rubric_cost_shape(
        small_rubric,
        review_text="workspace",
        answer_text="",
    )
    large = rh_full_rubric_cost_shape(
        large_rubric,
        review_text="workspace",
        answer_text="",
    )

    assert small.schema_bytes < 1_000
    assert large.schema_bytes < 1_000
    assert large.schema_bytes - small.schema_bytes < 10
    schema = rh_structured_output_schema(877, 2)
    schema_text = json.dumps(schema)
    assert "criterion_151" not in schema_text
    assert '"level"' not in schema_text
    assert schema["properties"]["criteria"]["minItems"] == 877
    assert schema["properties"]["criteria"]["maxItems"] == 877
    assert schema["properties"]["criteria"]["items"]["properties"][
        "level_index"
    ]["enum"] == [0, 1]
    payload = json.loads(rh_full_rubric_payload(large_rubric, "workspace", ""))
    contracts = payload["criterion_contracts"]
    assert [contract["criterion_id"] for contract in contracts] == [
        f"criterion_{index}" for index in range(1, 152)
    ]
    assert contracts[0]["level_options"] == [
        {"level_index": 0, "level": "A"},
        {"level_index": 1, "level": "B"},
    ]


def test_compact_parser_uses_position_and_level_index() -> None:
    levels = audit_module.parse_rubric_levels_strict(RUBRIC)
    assert parse_rh_structured_output(json.dumps(_wire_report()), levels) == _report()

    sparse_rubric = """RH audit sparse rubric.
Score normalization maximum: 2

Criterion 1: First.
Levels: A=1 B=0
[A]: Complete.
[B]: Missing.

Criterion 8: Second.
Levels: C=1 D=0
[C]: Complete.
[D]: Missing.
"""
    sparse_levels = audit_module.parse_rubric_levels_strict(sparse_rubric)
    sparse_wire = {
        "criteria": [
            {"level_index": 1, "reason": "The first item is missing."},
            {"level_index": 0, "reason": "The second item is complete."},
        ],
        "overall_reasoning": "The two positions map to different labels.",
    }
    assert parse_rh_structured_output(
        json.dumps(sparse_wire), sparse_levels
    )["criteria"] == {
        "criterion_1": {"level": "B", "reason": "The first item is missing."},
        "criterion_8": {"level": "C", "reason": "The second item is complete."},
    }

    invalid_level_index = deepcopy(_wire_report())
    invalid_level_index["criteria"][0]["level_index"] = 2
    with pytest.raises(FullRubricJudgeError, match="invalid level index"):
        parse_rh_structured_output(json.dumps(invalid_level_index), levels)

    invalid_keys = deepcopy(_wire_report())
    invalid_keys["criteria"][0]["criterion_id"] = "criterion_1"
    with pytest.raises(FullRubricJudgeError, match="invalid keys"):
        parse_rh_structured_output(json.dumps(invalid_keys), levels)

    with pytest.raises(FullRubricJudgeError, match="criterion count"):
        parse_rh_structured_output(
            json.dumps({"criteria": [], "overall_reasoning": "Missing."}),
            levels,
        )


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
                    text=json.dumps(_wire_report()),
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
        payload=rh_full_rubric_payload(RUBRIC, "workspace", ""),
        schema=rh_structured_output_schema(1, 2),
        repeat_index=0,
    )

    request = captured["request"]
    assert isinstance(request, dict)
    assert "temperature" not in request
    assert request["output_config"]["effort"] == "low"
    assert request["system"] == RH_FULL_RUBRIC_SYSTEM_PROMPT
    rendered_schema = request["output_config"]["format"]["schema"]
    assert "minItems" not in rendered_schema[
        "properties"
    ]["criteria"]
    assert "maxItems" not in rendered_schema[
        "properties"
    ]["criteria"]
    assert rendered_schema["properties"]["criteria"]["items"] == (
        rh_structured_output_schema(1, 2)["properties"]["criteria"]["items"]
    )
    assert spec.as_json()["temperature"] is None
    assert spec.as_json()["structured_output_contract"] == (
        RH_FULL_RUBRIC_ENGINE_IDENTITY["structured_output"]
    )
    assert spec.schema_bytes < 1_000
    assert generation.request_parameters["temperature"] is None


def test_rh_grading_normalizes_wire_reports_and_attests_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def generate(spec, *, payload, schema, repeat_index):
        calls.append((payload, schema))
        return FullRubricGeneration(
            text=json.dumps(_wire_report()),
            provider=spec.provider,
            requested_model=spec.requested_model,
            effective_model=spec.requested_model,
            response_id=f"response-{repeat_index}",
            request_parameters=audit_module._request_parameters(spec, repeat_index),
            usage={"input_tokens": 1, "output_tokens": 1},
        )

    monkeypatch.setattr(audit_module, "_generate_response", generate)
    records = grade_rh_full_rubric(
        rubric_text=RUBRIC,
        review_text="workspace",
        answer_text="",
        requested_model="claude-opus-5",
        api_base=None,
        seed=123,
    )

    assert len(calls) == 5
    assert all(
        json.loads(payload)["criterion_contracts"] == [{
            "criterion_id": "criterion_1",
            "level_options": [
                {"level_index": 0, "level": "A"},
                {"level_index": 1, "level": "B"},
            ],
        }]
        for payload, _schema in calls
    )
    assert records.score == 100
    structured = records.evaluation["full_rubric_structured"]
    assert structured["raw_reports"] == [_report() for _index in range(5)]
    assert structured["code_identity"] == RH_FULL_RUBRIC_ENGINE_IDENTITY
    assert records.usage["code_identity"] == RH_FULL_RUBRIC_ENGINE_IDENTITY


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
        return _records(**kwargs)

    monkeypatch.setattr(audit_module, "grade_rh_full_rubric", grade)
    attempt_id = "a" * 32
    invalid_root = judge._evaluation_root(submission, attempt_id)
    invalid_root.mkdir(parents=True)
    (invalid_root / "obsolete.json").write_text("{}")

    first = judge.evaluate(submission, attempt_id)
    second = judge.evaluate(submission, attempt_id)

    assert calls == 1
    assert not list(invalid_root.parent.glob(f"{attempt_id}.invalid-*"))
    assert first == second
    validation = json.loads(first.score_validation_path.read_text())
    assert validation["score"] == 100
    assert validation["engine_execution"]["temperature"] is None
    assert first.evaluation_path.is_file()


def test_audit_judge_serializes_concurrent_exact_evaluations(
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
    entered = threading.Event()
    release = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def grade(**kwargs):
        nonlocal calls
        with calls_lock:
            calls += 1
        entered.set()
        assert release.wait(timeout=5)
        return _records(**kwargs)

    monkeypatch.setattr(audit_module, "grade_rh_full_rubric", grade)
    attempt_id = "b" * 32
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(judge.evaluate, submission, attempt_id)
        assert entered.wait(timeout=5)
        second = pool.submit(judge.evaluate, submission, attempt_id)
        release.set()
        results = (first.result(timeout=5), second.result(timeout=5))

    assert calls == 1
    assert results[0] == results[1]
