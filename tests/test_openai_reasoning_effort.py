from __future__ import annotations

import pytest

from rubric_gen.runtime.llm import (
    OPENAI_REASONING_EFFORT_ENV,
    openai_reasoning_effort,
    request_parameters_for_model,
)
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    build_full_rubric_run_spec,
)


RUBRIC = """Score normalization maximum: 1\n\nCriterion 1: Do it.\nLevels: A=1 B=0\n[A]: Done.\n[B]: Missing.\n"""


def _full_rubric_effort() -> str | None:
    return build_full_rubric_run_spec(
        rubric_text=RUBRIC,
        review_text="evidence",
        answer_text="",
        requested_model="gpt-5.6-luna",
        seed=1,
    ).as_json()["reasoning_effort"]


def test_openai_reasoning_effort_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OPENAI_REASONING_EFFORT_ENV, raising=False)
    assert openai_reasoning_effort() == "none"
    assert request_parameters_for_model("gpt-5.6-luna")["reasoning_effort"] == "none"
    assert _full_rubric_effort() == "none"


def test_openai_reasoning_effort_accepts_explicit_xhigh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_REASONING_EFFORT_ENV, "xhigh")
    assert openai_reasoning_effort() == "xhigh"
    assert request_parameters_for_model("gpt-5.6-luna")["reasoning_effort"] == "xhigh"
    assert _full_rubric_effort() == "xhigh"


def test_openai_reasoning_effort_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPENAI_REASONING_EFFORT_ENV, "extreme")
    with pytest.raises(ValueError, match=OPENAI_REASONING_EFFORT_ENV):
        openai_reasoning_effort()
