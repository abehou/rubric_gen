from __future__ import annotations

import os
import types
from pathlib import Path

import openai
import pytest

from rubric_gen.biomnibench.judging.artifacts import JudgeArtifactStore
from rubric_gen.biomnibench.judging.llm_judge import (
    JudgePrompt,
    generate_response,
    provider_for_model,
)
from rubric_gen.biomnibench.judging.runner import BiomniBenchJudgeRunner


def test_judge_reads_a_stable_regular_review_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer\n")
    runner = object.__new__(BiomniBenchJudgeRunner)
    runner.config = types.SimpleNamespace(max_review_chars=None)
    runner.artifacts = JudgeArtifactStore(runner.config)

    workspace_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert runner._read_review_artifact(
            workspace, "answer.txt", root_fd=workspace_fd
        ) == "answer\n"
    finally:
        os.close(workspace_fd)


def test_vllm_judge_uses_openai_compatible_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            observed["client"] = kwargs
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=self.create)
            )

        @staticmethod
        def create(**kwargs: object) -> object:
            observed["request"] = kwargs
            return types.SimpleNamespace(
                id="response-id",
                model="Qwen/Qwen3.6-27B",
                choices=[types.SimpleNamespace(
                    message=types.SimpleNamespace(content='{"criteria": []}')
                )],
                usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            )

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("VLLM_BASE_URL", "http://qwen27:43117/v1")
    monkeypatch.delenv("VLLM_API_KEY", raising=False)

    result = generate_response(
        "Qwen/Qwen3.6-27B",
        JudgePrompt(instructions="Judge exactly.", evidence="Evidence."),
        ("criterion-1",),
    )

    assert result.provider == "vllm"
    assert result.text == '{"criteria": []}'
    assert observed["client"] == {
        "base_url": "http://qwen27:43117/v1/",
        "api_key": "EMPTY",
        "timeout": 300.0,
        "max_retries": 0,
    }
    request = observed["request"]
    assert isinstance(request, dict)
    assert request["model"] == "Qwen/Qwen3.6-27B"
    assert request["messages"] == [
        {"role": "system", "content": "Judge exactly."},
        {"role": "user", "content": "Evidence."},
    ]
    assert request["response_format"]["type"] == "json_schema"


def test_unknown_model_is_allowed_only_with_a_vllm_endpoint() -> None:
    assert provider_for_model("Qwen/Qwen3.6-35B-A3B", base_url="http://node/v1") == (
        "vllm"
    )
    with pytest.raises(ValueError, match="cannot infer"):
        provider_for_model("Qwen/Qwen3.6-35B-A3B")
