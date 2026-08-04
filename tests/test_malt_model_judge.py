from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from rubric_gen.malt import model_judge
from rubric_gen.malt.model_judge import (
    ModelGeneration,
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

    def generate(model: str, prompt: str) -> ModelGeneration:
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
        (output / "cases/case-a/gpt-test/generation.json").read_text()
    )
    assert generation["requested_model"] == "gpt-test"
    assert generation["effective_model"] == "gpt-test-served"
    assert (output / "run-provenance.json").is_file()


def test_direct_model_runner_retries_failed_member(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    calls = 0

    def generate(model: str, prompt: str) -> ModelGeneration:
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
    assert (output / "cases/case-a/gpt-test.failed-001").is_dir()


def test_category_failure_does_not_discard_completed_detection(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    category_calls = 0

    def generate(model: str, prompt: str) -> ModelGeneration:
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

    def generate(model: str, prompt: str) -> ModelGeneration:
        observed["prompt"] = prompt
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

    def generate(model: str, prompt: str) -> ModelGeneration:
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

    def vllm(model: str, prompt: str, url: str) -> ModelGeneration:
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

    def generate(model: str, prompt: str) -> ModelGeneration:
        observed["prompt"] = prompt
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

    def generate(model: str, prompt: str) -> ModelGeneration:
        observed["prompt"] = prompt
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

    def generate(model: str, prompt: str) -> ModelGeneration:
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

    (output / "cases/case-a/gpt-test/response.txt").write_text("tampered")
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

        def generate_content_response(self, prompt: str) -> object:
            observed["prompt"] = prompt
            observed["key"] = model_judge.os.environ["GEMINI_API_KEY"]
            return types.SimpleNamespace(
                text="response",
                model_version="gemini-test-served",
                response_id="gemini-response",
            )

    monkeypatch.setenv("GEMINI_API_KEY", "canonical-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "wrong-key")
    monkeypatch.setattr(model_judge, "GeminiClient", FakeGeminiClient)

    generation = model_judge.generate("gemini-test", "prompt")
    assert generation.text == "response"
    assert generation.effective_model == "gemini-test-served"
    assert generation.response_id == "gemini-response"
    assert observed == {
        "model": "gemini-test",
        "prompt": "prompt",
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

    generation = model_judge.generate("gpt-5.6-luna", "prompt")
    assert generation.text == "response"
    assert generation.effective_model == "gpt-5.6-luna-served"
    assert generation.response_id == "openai-response"
    assert observed["api_key"] == "openai-secret"
    assert observed["model"] == "gpt-5.6-luna"
    assert observed["input"] == "prompt"
    assert observed["max_output_tokens"] == 8_192
    assert observed["reasoning"] == {"effort": "medium"}
    assert observed["text"] == {"verbosity": "low"}
