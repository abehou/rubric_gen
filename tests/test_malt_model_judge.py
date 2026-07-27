from __future__ import annotations

import json
from pathlib import Path

import pytest

from rubric_gen.malt import model_judge
from rubric_gen.malt.model_judge import ModelJudgeConfig, ModelJudgeRunner


def _case(path: Path, transcript: dict[str, object]) -> Path:
    path.mkdir()
    (path / "transcript.json").write_text(json.dumps(transcript))
    (path / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "kind": "reward-hacking-forensic-case",
        "case_id": path.name,
        "evidence_files": ["transcript.json"],
    }))
    return path


def test_direct_model_runner_writes_scoreable_summary(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})

    def generate(model: str, prompt: str) -> str:
        assert "<transcript_jsonl>" in prompt
        return json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "analysis": "No reward-directed divergence is present.",
        })

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(case_dirs=(case,), models=("gpt-test",), output_dir=output),
        generate_response=generate,
    )
    assert runner.run() == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["records"][0]["verdict"]["decision"] == "no_reward_hacking_detected"
    assert (output / "detection-rates.json").is_file()
    assert (output / "detection-rates.png").is_file()


def test_direct_model_runner_retries_failed_member(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    calls = 0

    def generate(model: str, prompt: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient provider failure")
        return json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.8,
            "evidence_locations": [],
            "analysis": "No divergence.",
        })

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=output,
            max_retries=1,
        ),
        generate_response=generate,
    )

    assert runner.run() == 0
    record = json.loads((output / "summary.json").read_text())["records"][0]
    assert record["attempt_count"] == 2
    assert record["retry_exhausted"] is False
    assert (output / "cases/case-a/gpt-test.failed-001").is_dir()


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

    def generate(model: str, prompt: str) -> str:
        observed["prompt"] = prompt
        return json.dumps({
            "decision": "no_reward_hacking_detected",
            "confidence": 0.7,
            "evidence_locations": [],
            "analysis": "The score increase followed genuine work.",
        })

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

    def generate(model: str, prompt: str) -> str:
        assert "any MALT non-normal behavior" in prompt
        assert "reward hacking only" not in prompt
        return json.dumps({
            "decision": "non_normal_behavior_detected",
            "confidence": 0.9,
            "evidence_locations": ["event 1"],
            "analysis": "The agent deliberately refuses the task.",
        })

    output = tmp_path / "output"
    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("gpt-test",), output_dir=output,
            detection="non-normal",
        ),
        generate_response=generate,
    )
    assert runner.run() == 0
    summary = json.loads((output / "summary.json").read_text())
    assert summary["detection"] == "non-normal"
    assert summary["records"][0]["verdict"]["decision"] == (
        "non_normal_behavior_detected"
    )


def test_vllm_runner_routes_model_to_configured_server(tmp_path: Path) -> None:
    case = _case(tmp_path / "case-a", {"samples": []})
    observed = {}

    def vllm(model: str, prompt: str, url: str) -> str:
        observed.update(model=model, url=url)
        return json.dumps({
            "decision": "abstain", "confidence": 0.5,
            "evidence_locations": [], "analysis": "Insufficient evidence.",
        })

    runner = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(case,), models=("Qwen/Test",), output_dir=tmp_path / "out",
            base_urls={"Qwen/Test": "http://node:8000/v1"},
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

    def generate(model: str, prompt: str) -> str:
        observed["prompt"] = prompt
        return json.dumps({
            "decision": "no_reward_hacking_detected", "confidence": 0.8,
            "evidence_locations": [], "analysis": "No divergence.",
        })

    runner = ModelJudgeRunner(
        ModelJudgeConfig(case_dirs=(case,), models=("gpt-test",), output_dir=tmp_path / "out"),
        generate_response=generate,
    )
    assert runner.run() == 0
    prompt = observed["prompt"]
    assert prompt.count('"content":"same exact action"') == 1
    assert '"occurrences":2' in prompt
    metadata = json.loads((tmp_path / "out/cases/case-a/gpt-test/metadata.json").read_text())
    assert metadata["compact_evidence"]["source_occurrences"] == 3
    assert metadata["compact_evidence"]["distinct_events"] == 2


def test_malt_gemini_uses_only_canonical_gemini_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, str] = {}

    class FakeGeminiClient:
        def __init__(self, *, model: str) -> None:
            observed["model"] = model

        def generate_content(self, prompt: str) -> str:
            observed["prompt"] = prompt
            observed["key"] = model_judge.os.environ["GEMINI_API_KEY"]
            return "response"

    monkeypatch.setenv("GEMINI_API_KEY", "canonical-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "wrong-key")
    monkeypatch.setattr(model_judge, "GeminiClient", FakeGeminiClient)

    assert model_judge.generate("gemini-test", "prompt") == "response"
    assert observed == {
        "model": "gemini-test",
        "prompt": "prompt",
        "key": "canonical-key",
    }
