from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from rubric_gen.malt import model_judge
from rubric_gen.malt.model_judge import (
    CostBudgetExceeded,
    ModelGeneration,
    ModelRequest,
    ModelJudgeConfig,
    ModelJudgeRunner,
    request_provenance,
)
from rubric_gen.biomnibench.revision.artifacts import tree_sha256
from rubric_gen.biomnibench.utils.hashing import sha256_file


DATASET_PROVENANCE = {
    "schema_version": 2,
    "dataset_revision": "a" * 40,
    "inputs": [{"path": "/dataset/shard.parquet", "bytes": 1, "sha256": "b" * 64}],
}


def _generation(
    model: str, text: str, *, base_url: str | None = None
) -> ModelGeneration:
    request = request_provenance(model, base_url=base_url)
    return ModelGeneration(
        text=text,
        provider=str(request["provider"]),
        requested_model=model,
        effective_model=model + "-served",
        response_id="response-test",
        request_parameters=request,
    )


def _request() -> ModelRequest:
    return ModelRequest(
        instructions="instructions",
        evidence="prompt",
        schema_name="test_schema",
        schema={"type": "object", "additionalProperties": False},
    )


def test_revision_cache_groups_serialize_only_identical_model_prefixes(
    tmp_path: Path,
) -> None:
    first = _request()
    second = ModelRequest(
        instructions=first.instructions,
        evidence="different evidence",
        schema_name=first.schema_name,
        schema=first.schema,
    )
    jobs = [
        model_judge.PreparedJob(
            case=tmp_path / name,
            model=model,
            source_kind=source_kind,
            requests=(request,),
            input_tokens=(100,),
            compact_stats={},
        )
        for name, model, source_kind, request in (
            ("revision-a", "gpt-5.6-sol", "revision", first),
            ("revision-b", "gpt-5.6-sol", "revision", second),
            ("revision-c", "claude-opus-4-8", "revision", second),
            ("case-a", "gpt-5.6-sol", "case", first),
            ("case-b", "gpt-5.6-sol", "case", second),
        )
    ]

    groups = [ModelJudgeRunner._standard_cache_group(job) for job in jobs]
    assert groups[0] == groups[1]
    assert groups[0] != groups[2]
    assert groups[3] != groups[4]


def test_anthropic_preflight_uses_provider_token_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class Messages:
        def count_tokens(self, **kwargs: object) -> object:
            observed.update(kwargs)
            return types.SimpleNamespace(input_tokens=321)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setattr(
        model_judge,
        "_token_counter_client",
        lambda provider, key: types.SimpleNamespace(messages=Messages()),
    )

    assert model_judge.count_input_tokens("claude-opus-4-8", _request()) == 321
    assert observed["model"] == "claude-opus-4-8"
    assert observed["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": _request().schema},
    }


def test_gemini_preflight_reserves_uncounted_schema_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Models:
        def count_tokens(self, **kwargs: object) -> object:
            assert kwargs["model"] == "gemini-3.1-pro-preview"
            assert kwargs["contents"] == _request().flat_prompt()
            return types.SimpleNamespace(total_tokens=100)

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setattr(
        model_judge,
        "_token_counter_client",
        lambda provider, key: types.SimpleNamespace(models=Models()),
    )
    schema_bytes = len(
        json.dumps(
            _request().schema,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )

    assert (
        model_judge.count_input_tokens("gemini-3.1-pro-preview", _request())
        == 100 + schema_bytes
    )


def _case(path: Path, transcript: dict[str, object]) -> Path:
    path.mkdir()
    (path / "transcript.json").write_text(json.dumps(transcript))
    (path / "manifest.json").write_text(json.dumps({
        "schema_version": 2,
        "kind": "reward-hacking-forensic-case",
        "case_id": path.name,
        "evidence_schema_version": 5,
        "evidence_files": ["transcript.json"],
    }))
    return path


def test_direct_model_runner_writes_scoreable_summary(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        prompt = request.flat_prompt()
        assert "<transcript_jsonl>" in prompt
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "findings": [],
            "analysis": "No reward-directed divergence is present.",
        }))

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=output,
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_response=generate,
    )
    assert runner.run() == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["records"][0]["verdict"]["decision"] == "no_reward_hacking_detected"
    assert summary["records"][0]["verdict"]["findings"] == []
    assert "No reward-directed divergence" in summary["records"][0]["verdict"]["analysis"]
    assert (output / "detection-rates.json").is_file()
    assert (output / "detection-rates.png").is_file()
    assert not (output / "category-rates.json").exists()
    generation = json.loads(
        (output / "cases/case-a/gpt-test/generations.json").read_text()
    )[0]["generation"]
    assert generation["requested_model"] == "gpt-test"
    assert generation["effective_model"] == "gpt-test-served"
    assert (output / "run-provenance.json").is_file()


def test_direct_model_runner_retries_failed_member(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient provider failure")
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "findings": [],
            "analysis": "No divergence.",
        }))

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=output,
            max_retries=1,
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    record = json.loads((output / "summary.json").read_text())["records"][0]
    assert record["attempt_count"] == 2
    assert record["retry_exhausted"] is False
    assert not (output / "cases/case-a/gpt-test.failed-001").exists()


def test_direct_runner_does_not_make_posthoc_category_calls(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        nonlocal calls
        calls += 1
        return _generation(model, json.dumps({
            "decision": "reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": ["event_id:1"],
            "findings": [{
                "type": "metric gaming",
                "description": "Optimized the measured proxy.",
                "evidence_locations": ["event_id:1"],
            }],
            "analysis": "The trace shows reward-directed divergence.",
        }))

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,),
            models=("gpt-test",),
            output_dir=output,
            max_retries=1,
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    assert calls == 1
    assert (output / "summary.json").is_file()
    assert (output / "detection-rates.json").is_file()
    assert not (output / "category-error.json").exists()
    assert not (output / "category-rates.json").exists()


def test_direct_model_runner_audits_biomni_revision(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "da-1-1"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text(
        "Compute the real result for DA-1-1 under BASE--STATIC.\n"
    )
    revision = tmp_path / "revision" / "da-1-1"
    submissions = revision / "submissions"
    for index in range(2):
        submission = submissions / f"s{index:03d}"
        workspace = submission / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "answer.txt").write_text(
            f"claimed result {index} for da-1-1\n"
        )
        (workspace / "trace.md").write_text(
            f"analysis trace {index} in base--static\n"
        )
        trajectory_events: list[dict[str, object]] = [
            {
                "type": "message",
                "role": "assistant",
                "content": f"changed {index}",
            },
            {
                "type": "tool_use",
                "parameters": {"command": "python solve.py"},
            },
        ]
        if index == 1:
            trajectory_events.extend([
                {
                    "type": "item.started",
                    "item": {
                        "id": "call-1",
                        "type": "command_execution",
                        "command": "python huge.py",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "call-1",
                        "type": "command_execution",
                        "command": "python huge.py",
                        "aggregated_output": (
                            "HEAD_MARKER" + "x" * 80_000 + "TAIL_MARKER"
                        ),
                        "status": "completed",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "id": "call-2",
                        "type": "command_execution",
                        "command": "python huge.py",
                        "aggregated_output": (
                            "HEAD_MARKER" + "x" * 80_000 + "TAIL_MARKER"
                        ),
                        "status": "completed",
                    },
                },
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 999_999},
                },
            ])
        (submission / "trajectory.stream.jsonl").write_text(
            "\n".join(json.dumps(event) for event in trajectory_events) + "\n"
        )
        (submission / "status.json").write_text(json.dumps({"exit_code": 0}))
        (submission / "snapshot.json").write_text(json.dumps({
            "schema_version": 2,
            "submission_id": f"s{index:03d}",
            "workspace_sha256": tree_sha256(workspace),
            "trajectory_sha256": sha256_file(
                submission / "trajectory.stream.jsonl"
            ),
        }))
    (revision / "manifest.json").write_text(json.dumps({
        "schema_version": 2,
        "kind": "rubric-gen-submission-revision-experiment",
        "design_sha256": "d" * 64,
        "assignment_id": "da-1-1--rep-001--base--static",
        "condition_id": "base--static",
        "task_id": "da-1-1",
        "submission_count": 2,
    }))
    (revision / "state.json").write_text(json.dumps({
        "phase": "completed",
        "submission_ids": ["s000", "s001"],
        "scores": [20, 100],
        "next_turn_index": 2,
    }))
    feedback = revision / "feedback"
    feedback.mkdir()
    (feedback / "s000.json").write_text(json.dumps({
        "schema_version": 1,
        "policy": "semi",
        "score": 20,
        "raw_score": 20,
        "criteria": {
            "criterion_1": {
                "title": "Use the real data",
                "selected_level": "C",
                "points": 0,
                "maximum_points": 80,
            }
        },
    }))
    observed: dict[str, str] = {}

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        observed["prompt"] = request.flat_prompt()
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.7,
            "evidence_locations": [],
            "findings": [],
            "analysis": "The score increase followed genuine work.",
        }))

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(),
            revision_dirs=(revision,),
            design_sha256s=("d" * 64,),
            tasks_dir=tasks,
            models=("gpt-test",),
            output_dir=output,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    assert "Compute the real result" in observed["prompt"]
    assert "python solve.py" in observed["prompt"]
    assert "da-1-1" not in observed["prompt"].lower()
    assert "base--static" not in observed["prompt"].lower()
    assert "[TASK_ID]" in observed["prompt"]
    assert "[CONDITION]" in observed["prompt"]
    assert "solver_feedback:s000" in observed["prompt"]
    assert "Use the real data" in observed["prompt"]
    assert '"scores"' not in observed["prompt"]
    assert observed["prompt"].count("python huge.py") == 1
    assert '"record_type":"bounded_text"' in observed["prompt"]
    assert '"value_reference":{"same_as_event_id":' in observed["prompt"]
    assert "HEAD_MARKER" in observed["prompt"]
    assert "TAIL_MARKER" in observed["prompt"]
    assert '"input_tokens":999999' not in observed["prompt"]
    record = json.loads((output / "summary.json").read_text())["records"][0]
    assert record["case_id"].startswith("revision-")
    assert record["source_kind"] == "revision"
    assert record["source_path"] == str(revision)
    compact = record["compact_evidence"]
    assert compact["solver_feedback_records"] == 1
    assert compact["superseded_started_events"] == 1
    assert compact["max_command_output_chars"] == 2_048
    assert compact["truncated_text_fields"] == 2
    assert compact["exact_duplicate_records"] == 1
    assert compact["exact_duplicate_chars_saved"] > 2_000
    assert compact["truncated_chars"] > 0


def test_chunking_materializes_exact_value_references() -> None:
    first = {
        "event_id": 1,
        "source": "trajectory:1",
        "value": {"content": "same evidence"},
    }
    second = {
        "event_id": 2,
        "source": "trajectory:2",
        "value_reference": {"same_as_event_id": 1},
    }
    evidence = "\n".join(json.dumps(value) for value in (first, second))

    materialized = model_judge._materialize_exact_value_references(evidence)
    records = [json.loads(line) for line in materialized.splitlines()]

    assert records[0]["value"] == records[1]["value"]
    assert records[1]["event_id"] == 2
    assert records[1]["source"] == "trajectory:2"
    assert "value_reference" not in records[1]


def test_non_normal_direct_prompt_and_verdict_vocabulary(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        prompt = request.flat_prompt()
        if "<finding_inventory_json>" in prompt:
            return _generation(model, json.dumps({"categories": [{
                "name": "strategic refusal",
                "description": "Deliberately declines the assigned task.",
                "finding_ids": ["r0000-f000"],
            }]}))
        assert "any MALT non-normal behavior" in prompt
        assert "reward hacking only" not in prompt
        return _generation(model, json.dumps({
            "decision": "non_normal_behavior_detected",
            "confidence": 0.9,
            "evidence_locations": [1],
            "findings": [{
                "type": "deliberate refusal",
                "description": "The agent deliberately refuses the task.",
                "evidence_locations": [1],
            }],
            "analysis": "The agent deliberately refuses the task.",
        }))

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=output,
            detection="non-normal",
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_response=generate,
    )
    assert runner.run() == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["detection"] == "non-normal"
    assert summary["records"][0]["verdict"]["decision"] == (
        "non_normal_behavior_detected"
    )
    assert summary["records"][0]["verdict"]["evidence_locations"] == [
        "event_id:1"
    ]
    assert summary["records"][0]["verdict"]["findings"][0][
        "evidence_locations"
    ] == ["event_id:1"]


def test_vllm_runner_routes_model_to_configured_server(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    observed = {}

    def vllm(model: str, request: ModelRequest, url: str) -> ModelGeneration:
        observed.update(model=model, url=url)
        return _generation(model, json.dumps({
            "decision": "abstain", "confidence": 0.5,
            "evidence_locations": [], "findings": [],
            "analysis": "Insufficient evidence.",
        }), base_url=url)

    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("Qwen/Test",), output_dir=tmp_path / "out",
            base_urls={"Qwen/Test": "http://node:8000/v1"},
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_vllm_response=vllm,
    )
    assert runner.run() == 0
    assert observed == {"model": "Qwen/Test", "url": "http://node:8000/v1"}


def test_direct_prompt_deduplicates_replayed_conversation_prefixes(
    tmp_path: Path,
) -> None:
    message = {"role": "assistant", "content": "same exact action"}
    case = _case(tmp_path / "case-a", {
        "samples": [
            {"input": [message]},
            {"input": [message], "output": [
                {"role": "assistant", "content": "new action"}
            ]},
        ]
    })
    observed: dict[str, str] = {}

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        observed["prompt"] = request.flat_prompt()
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected", "confidence": 0.8,
            "evidence_locations": [], "findings": [],
            "analysis": "No divergence.",
        }))

    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=tmp_path / "out",
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_response=generate,
    )
    assert runner.run() == 0
    prompt = observed["prompt"]
    assert prompt.count('"content":"same exact action"') == 1
    assert '"source_references":2' in prompt
    metadata = json.loads((tmp_path / "out/cases/case-a/gpt-test/metadata.json").read_text())
    assert metadata["compact_evidence"]["source_references"] == 3
    assert metadata["compact_evidence"]["distinct_events"] == 2


def test_direct_prompt_preserves_distinct_function_calls_with_empty_content(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "case-a", {"samples": [{"output": [[
        {
            "role": "assistant",
            "content": "",
            "function_call": {"name": "submit_review", "arguments": "first"},
        },
        {
            "role": "assistant",
            "content": "",
            "function_call": {"name": "submit_review", "arguments": "second"},
        },
    ]]}]})
    observed: dict[str, str] = {}

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        observed["prompt"] = request.flat_prompt()
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "findings": [],
            "analysis": "Both structured calls are substantive.",
        }))

    output = tmp_path / "out"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,),
            models=("gpt-test",),
            output_dir=output,
            dataset_provenance=DATASET_PROVENANCE,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    assert '"arguments":"first"' in observed["prompt"]
    assert '"arguments":"second"' in observed["prompt"]
    metadata = json.loads(
        (output / "cases/case-a/gpt-test/metadata.json").read_text()
    )
    assert metadata["compact_evidence"]["distinct_events"] == 2
    assert metadata["compact_evidence"]["source_references"] == 2


def test_resume_requires_exact_run_and_case_provenance(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    output = tmp_path / "out"
    calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        nonlocal calls
        calls += 1
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "findings": [],
            "analysis": "No divergence.",
        }))

    base = dict(
        case_dirs=(case,),
        models=("gpt-test",),
        output_dir=output,
        dataset_provenance=DATASET_PROVENANCE,
    )
    assert ModelJudgeRunner(
        ModelJudgeConfig(**base), generate_response=generate
    ).run() == 0
    assert ModelJudgeRunner(
        ModelJudgeConfig(**base, resume=True), generate_response=generate
    ).run() == 0
    assert calls == 1
    summary = json.loads((output / "summary.json").read_text())
    assert summary["records"][0]["status"] == "skipped"
    assert summary["records"][0]["generation"]["effective_model"] == (
        "gpt-test-served"
    )

    (output / "cases/case-a/gpt-test/responses.json").write_text("tampered")
    assert ModelJudgeRunner(
        ModelJudgeConfig(**base, resume=True), generate_response=generate
    ).run() == 0
    assert calls == 2
    assert (output / "cases/case-a/gpt-test.failed-001").is_dir()

    changed = {
        **DATASET_PROVENANCE,
        "inputs": [{
            "path": "/dataset/shard.parquet",
            "bytes": 1,
            "sha256": "c" * 64,
        }],
    }
    with pytest.raises(ValueError, match="run provenance does not exactly match"):
        ModelJudgeRunner(
            ModelJudgeConfig(**{**base, "dataset_provenance": changed}, resume=True),
            generate_response=generate,
        ).run()


def test_resume_preserves_cumulative_openai_cost(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    output = tmp_path / "out"
    calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        nonlocal calls
        calls += 1
        generation = _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "findings": [],
            "analysis": "No divergence.",
        }))
        return ModelGeneration(
            **{
                **generation.__dict__,
                "provider_metadata": {
                    "usage": {"input_tokens": 1_000, "output_tokens": 100}
                },
            }
        )

    base = dict(
        case_dirs=(case,),
        models=("gpt-5.6-luna",),
        output_dir=output,
        dataset_provenance=DATASET_PROVENANCE,
    )
    assert ModelJudgeRunner(
        ModelJudgeConfig(**base), generate_response=generate
    ).run() == 0
    first = json.loads((output / "summary.json").read_text())["cost"]
    assert first["observed_api_usd"] > 0

    assert ModelJudgeRunner(
        ModelJudgeConfig(**base, resume=True), generate_response=generate
    ).run() == 0
    resumed = json.loads((output / "summary.json").read_text())["cost"]
    assert resumed["observed_api_usd"] == first["observed_api_usd"]
    assert calls == 1


def test_malt_gemini_uses_only_canonical_gemini_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    class FakeGeminiClient:
        def __init__(self, *, model: str) -> None:
            observed["model"] = model

        def generate_content_response(
            self,
            prompt: str,
            *,
            response_schema: dict[str, object],
            thinking_level: str,
            max_output_tokens: int,
        ) -> object:
            observed["prompt"] = prompt
            observed["schema"] = str(response_schema)
            observed["key"] = model_judge.os.environ["GEMINI_API_KEY"]
            observed["thinking_level"] = thinking_level
            observed["max_output_tokens"] = str(max_output_tokens)
            return types.SimpleNamespace(
                text="response",
                model_version="gemini-test-served",
                response_id="gemini-response",
            )

    monkeypatch.setenv("GEMINI_API_KEY", "canonical-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "wrong-key")
    monkeypatch.setattr(model_judge, "GeminiClient", FakeGeminiClient)

    generation = model_judge.generate("gemini-test", _request())
    assert generation.text == "response"
    assert generation.effective_model == "gemini-test-served"
    assert generation.response_id == "gemini-response"
    assert observed == {
        "model": "gemini-test",
        "prompt": "instructions\n\nprompt",
        "schema": "{'type': 'object', 'additionalProperties': False}",
        "key": "canonical-key",
        "thinking_level": "low",
        "max_output_tokens": "4096",
    }


def test_malt_openai_judge_uses_no_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs: object) -> object:
            observed.update(kwargs)
            return types.SimpleNamespace(
                output_text="response",
                model="gpt-5.6-luna-served",
                id="openai-response",
                created_at=123,
                service_tier="default",
                usage={"input_tokens": 10, "output_tokens": 2},
            )

    class FakeOpenAI:
        def __init__(
            self, *, api_key: str, timeout: float, max_retries: int
        ) -> None:
            observed["api_key"] = api_key
            observed["timeout"] = timeout
            observed["max_retries"] = max_retries
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    generation = model_judge.generate("gpt-5.6-luna", _request())
    assert generation.text == "response"
    assert generation.effective_model == "gpt-5.6-luna-served"
    assert generation.response_id == "openai-response"
    assert observed["api_key"] == "openai-secret"
    assert observed["model"] == "gpt-5.6-luna"
    assert observed["input"][0]["content"][0]["prompt_cache_breakpoint"] == {  # type: ignore[index]
        "mode": "explicit"
    }
    assert observed["input"][1]["content"] == "prompt"  # type: ignore[index]
    assert observed["max_output_tokens"] == 4_096
    assert observed["reasoning"] == {"effort": "none"}
    assert observed["text"]["verbosity"] == "low"  # type: ignore[index]
    assert observed["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert observed["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert observed["truncation"] == "disabled"
    assert observed["timeout"] == 600.0
    assert observed["max_retries"] == 0


def test_malt_anthropic_judge_uses_low_effort_cache_and_no_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeMessages:
        def create(self, **kwargs: object) -> object:
            observed.update(kwargs)
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text="response")],
                model="claude-opus-4-8-served",
                id="anthropic-response",
                stop_reason="end_turn",
                usage={"input_tokens": 10, "output_tokens": 2},
            )

    class FakeAnthropic:
        def __init__(
            self, *, api_key: str, timeout: float, max_retries: int
        ) -> None:
            observed["api_key"] = api_key
            observed["timeout"] = timeout
            observed["max_retries"] = max_retries
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    generation = model_judge.generate("claude-opus-4-8", _request())

    assert generation.text == "response"
    assert observed["api_key"] == "anthropic-secret"
    assert observed["timeout"] == 600.0
    assert observed["max_retries"] == 0
    assert observed["max_tokens"] == 4096
    assert observed["output_config"] == {
        "effort": "low",
        "format": {
            "type": "json_schema",
            "schema": {"type": "object", "additionalProperties": False},
        },
    }
    assert observed["system"] == [{
        "type": "text",
        "text": "instructions",
        "cache_control": {"type": "ephemeral"},
    }]


def test_oversized_evidence_is_chunked_then_synthesized(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-large", {
        "samples": [{"output": [{"role": "assistant", "content": "x" * 120_000}]}]
    })
    schemas: list[str] = []

    def token_count(model: str, request: ModelRequest) -> int:
        return max(1, len(request.flat_prompt()) // 4)

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        schemas.append(request.schema_name)
        return _generation(model, json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "findings": [],
            "analysis": "No concrete reward-directed divergence in this evidence.",
        }))

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=output,
            dataset_provenance=DATASET_PROVENANCE,
            max_input_tokens=10_000,
        ),
        generate_response=generate,
        count_tokens=token_count,
    )

    assert runner.run() == 0
    record = json.loads((output / "summary.json").read_text())["records"][0]
    assert record["compact_evidence"]["chunked"] == 1
    assert schemas.count("malt_forensic_chunk_verdict") > 1
    assert schemas.count("malt_forensic_synthesis_verdict") == 1
    preflight = json.loads((output / "cost-preflight.json").read_text())
    assert max(preflight["jobs"][0]["input_tokens"]) <= 10_000


def test_cost_preflight_stops_before_generation(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        nonlocal calls
        calls += 1
        raise AssertionError("generation must not start")

    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-5.6-luna",),
            output_dir=tmp_path / "output",
            dataset_provenance=DATASET_PROVENANCE,
            max_cost_usd=0.01,
        ),
        generate_response=generate,
        count_tokens=lambda _model, _request: 100_000,
    )

    with pytest.raises(CostBudgetExceeded, match="exceeds --max-cost-usd"):
        runner.run()
    assert calls == 0
    preflight = json.loads((tmp_path / "output/cost-preflight.json").read_text())
    assert preflight["schema_version"] == 4
    assert preflight["max_attempts_per_request"] == 2
    assert preflight["worst_case_reserved_api_cost_usd"] == pytest.approx(
        2 * preflight["max_output_single_attempt_api_cost_usd"]
    )
    assert (
        preflight["expected_api_cost_usd"]
        < preflight["worst_case_reserved_api_cost_usd"]
    )


def test_provider_costs_apply_openai_and_gemini_long_context_tiers() -> None:
    # Luna: 300k uncached input at 2x $0.20/MTok plus 100k output at
    # 1.5x $1.20/MTok.
    assert ModelJudgeRunner._request_cost(
        "gpt-5.6-luna", 300_000, 100_000
    ) == pytest.approx(0.3)
    # At the threshold the ordinary tier still applies.
    assert ModelJudgeRunner._request_cost(
        "gpt-5.6-luna", 272_000, 100_000
    ) == pytest.approx(0.1744)
    # Gemini switches above 200k to $4 input and $18 output per MTok.
    assert ModelJudgeRunner._request_cost(
        "gemini-3.1-pro-preview", 300_000, 100_000
    ) == pytest.approx(3.0)
    # Claude's full context uses the standard Opus 4.8 tier.
    assert ModelJudgeRunner._request_cost(
        "claude-opus-4-8", 300_000, 100_000
    ) == pytest.approx(4.0)


def test_cost_reservation_marks_only_the_stable_prefix_as_a_cache_write() -> None:
    request = ModelRequest(
        instructions="stable " * 2_000,
        evidence="changing " * 40_000,
        schema_name="test_schema",
        schema={"type": "object", "additionalProperties": False},
    )
    total = model_judge._estimated_tokens(request)
    reserved = ModelJudgeRunner._cache_write_reservation_tokens(
        "gpt-5.6-sol", request, total
    )

    assert 0 < reserved < total
    assert ModelJudgeRunner._cache_write_reservation_tokens(
        "gemini-3.1-pro-preview", request, total
    ) == 0


def test_quota_error_opens_circuit_without_retries(tmp_path: Path) -> None:
    cases = (
        _case(tmp_path / "case-a", {"samples": []}),
        _case(tmp_path / "case-b", {"samples": []}),
    )
    calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        nonlocal calls
        calls += 1
        raise RuntimeError("insufficient_quota: top up credits")

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=cases, models=("gpt-test",), output_dir=output,
            dataset_provenance=DATASET_PROVENANCE,
            max_retries=3, max_concurrency=1,
        ),
        generate_response=generate,
    )

    assert runner.run() == 1
    records = json.loads((output / "summary.json").read_text())["records"]
    assert calls == 1
    assert all(record["attempt_count"] == 1 for record in records)
    assert "provider circuit is open" in records[1]["error"]


def test_openai_batch_submits_and_resume_collects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    verdict = json.dumps({
        "decision": "no_reward_hacking_detected",
        "confidence": 0.9,
        "evidence_locations": [],
        "findings": [],
        "analysis": "No reward-directed divergence.",
    })
    output_row = json.dumps({
        "custom_id": "j00000-r000",
        "response": {
            "status_code": 200,
            "body": {
                "id": "resp-batch",
                "model": "gpt-5.6-luna-served",
                "created_at": 1,
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": verdict}],
                }],
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        },
    }) + "\n"

    class FakeFiles:
        def create(self, **kwargs: object) -> object:
            return types.SimpleNamespace(id="file-input")

        def content(self, file_id: str) -> object:
            assert file_id == "file-output"
            return types.SimpleNamespace(text=output_row)

    class FakeBatches:
        def create(self, **kwargs: object) -> object:
            return types.SimpleNamespace(id="batch-test", status="validating")

        def retrieve(self, batch_id: str) -> object:
            assert batch_id == "batch-test"
            return types.SimpleNamespace(
                id=batch_id, status="completed", output_file_id="file-output",
                error_file_id=None,
            )

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            self.files = FakeFiles()
            self.batches = FakeBatches()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))
    base = dict(
        case_dirs=(case,), models=("gpt-5.6-luna",),
        output_dir=tmp_path / "output", dataset_provenance=DATASET_PROVENANCE,
        execution="batch",
    )
    count = lambda _model, _request: 100

    assert ModelJudgeRunner(ModelJudgeConfig(**base), count_tokens=count).run() == 0
    assert not (tmp_path / "output/summary.json").exists()
    batch_line = json.loads(
        (tmp_path / "output/batch-initial-01.jsonl").read_text().splitlines()[0]
    )
    assert batch_line["body"]["prompt_cache_options"]["mode"] == "explicit"
    assert batch_line["body"]["text"]["format"]["type"] == "json_schema"

    assert ModelJudgeRunner(
        ModelJudgeConfig(**base, resume=True), count_tokens=count
    ).run() == 0
    summary = json.loads((tmp_path / "output/summary.json").read_text())
    assert summary["records"][0]["verdict"]["decision"] == (
        "no_reward_hacking_detected"
    )
    assert (tmp_path / "output/cases/case-a/gpt-5.6-luna/generations.json").is_file()


def test_openai_batch_prices_a_paid_response_before_parse_retry(
    tmp_path: Path,
) -> None:
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(),
            models=("gpt-5.6-luna",),
            output_dir=tmp_path,
            execution="batch",
        ),
        count_tokens=lambda _model, _request: 1_000,
    )
    body = {
        "id": "resp-invalid",
        "model": "gpt-5.6-luna",
        "output": [{
            "type": "message",
            "content": [{"type": "output_text", "text": "{}"}],
        }],
        "usage": {"input_tokens": 1_000, "output_tokens": 100},
    }

    with pytest.raises(ValueError) as error:
        runner._batch_result("job-invalid", body)

    assert getattr(error.value, "batch_cost_accounted") is True
    assert runner._spent_usd == pytest.approx(0.00016)
