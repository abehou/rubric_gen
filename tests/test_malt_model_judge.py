from __future__ import annotations

import json
from pathlib import Path

import pytest

from rubric_gen.malt import model_judge
from rubric_gen.malt.model_judge import ModelJudgeConfig, ModelJudgeRunner


def test_direct_model_runner_writes_scoreable_summary(tmp_path: Path) -> None:
    case = tmp_path / "case-a"
    case.mkdir()
    (case / "transcript.json").write_text(json.dumps({"samples": []}))

    def generate(model: str, prompt: str) -> str:
        assert "<transcript>" in prompt
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


def test_vllm_runner_routes_model_to_configured_server(tmp_path: Path) -> None:
    case = tmp_path / "case-a"
    case.mkdir()
    (case / "transcript.json").write_text('{"samples": []}')
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
