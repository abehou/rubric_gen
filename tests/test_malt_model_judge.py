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
    assert (output / "category-rates.json").is_file()
    assert (output / "category-rates.png").is_file()
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


def test_category_failure_does_not_discard_completed_detection(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    category_calls = 0

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        prompt = request.flat_prompt()
        nonlocal category_calls
        if "<finding_inventory_json>" in prompt:
            category_calls += 1
            return _generation(model, '{"categories": []}')
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
    assert category_calls == 2
    assert (output / "summary.json").is_file()
    assert (output / "detection-rates.json").is_file()
    assert (output / "category-error.json").is_file()
    assert not (output / "category-rates.json").exists()


def test_direct_model_runner_audits_biomni_revision(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "da-1-1"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("Compute the real result.\n")
    revision = tmp_path / "revision" / "da-1-1"
    submission = revision / "submissions" / "s001"
    workspace = submission / "workspace"
    workspace.mkdir(parents=True)
    (revision / "feedback").mkdir()
    (revision / "manifest.json").write_text(json.dumps({
        "kind": "rubric-gen-submission-revision-experiment",
        "task_id": "da-1-1",
    }))
    (revision / "state.json").write_text(json.dumps({"scores": [20, 100]}))
    (revision / "feedback" / "s000.json").write_text(
        json.dumps({"score": 20})
    )
    (submission / "trajectory.stream.jsonl").write_text(
        json.dumps({"type": "message", "role": "assistant", "content": "changed"})
        + "\n"
        + json.dumps({"type": "tool_use", "parameters": {"command": "python solve.py"}})
        + "\n"
    )
    (workspace / "answer.txt").write_text("claimed result\n")
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
            tasks_dir=tasks,
            models=("gpt-test",),
            output_dir=output,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    assert "Compute the real result" in observed["prompt"]
    assert "python solve.py" in observed["prompt"]
    assert "feedback/s000.json" in observed["prompt"]
    record = json.loads((output / "summary.json").read_text())["records"][0]
    assert record["case_id"] == "da-1-1"
    assert record["source_kind"] == "revision"
    assert record["source_path"] == str(revision)


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


def test_malt_gemini_uses_only_canonical_gemini_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    class FakeGeminiClient:
        def __init__(self, *, model: str) -> None:
            observed["model"] = model

        def generate_content_response(
            self, prompt: str, *, response_schema: dict[str, object]
        ) -> object:
            observed["prompt"] = prompt
            observed["schema"] = str(response_schema)
            observed["key"] = model_judge.os.environ["GEMINI_API_KEY"]
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
    }


def test_malt_openai_judge_uses_medium_reasoning_effort(
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
        def __init__(self, *, api_key: str) -> None:
            observed["api_key"] = api_key
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
    assert observed["reasoning"] == {"effort": "medium"}
    assert observed["text"]["verbosity"] == "low"  # type: ignore[index]
    assert observed["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert observed["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert observed["truncation"] == "disabled"


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
        def __init__(self, *, api_key: str) -> None:
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
