from __future__ import annotations

from pathlib import Path

import pytest

from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.rubrics.generator import (
    DEFAULT_MODELS,
    RubricGenerationConfig,
    generation_prompt,
    default_generation_dir,
)
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT


def test_generate_cli_selects_harness_and_model(tmp_path: Path) -> None:
    task = tmp_path / "da-1-1"
    args = build_parser().parse_args(
        [
            "generate",
            str(task),
            "--output-dir",
            str(tmp_path / "out"),
            "--harness",
            "claude-code",
            "--model",
            "claude-test",
        ]
    )

    config = RubricGenerationConfig.from_namespace(args)

    assert config.task_dirs == (task,)
    assert config.harness == "claude-code"
    assert config.effective_model == "claude-test"


@pytest.mark.parametrize("harness", sorted(DEFAULT_MODELS))
def test_generate_has_harness_specific_default_models(
    tmp_path: Path, harness: str
) -> None:
    config = RubricGenerationConfig(
        task_dirs=(tmp_path / "da-1-1",),
        output_dir=tmp_path / "out",
        harness=harness,
    )
    assert config.effective_model == DEFAULT_MODELS[harness]


def test_generation_prompt_requires_exploration_without_fixed_score_schema() -> None:
    prompt = generation_prompt("da-1-1")

    assert "inspect the files under data/" in prompt
    assert "Attempt a tentative solution" in prompt
    assert "generated_rubric.md" in prompt
    assert "solution_notes.md" in prompt
    assert "Do not force A/B/C tiers" in prompt
    assert "tests/rubric.txt" in prompt


def test_generate_rejects_task_with_all(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        [
            "generate",
            str(tmp_path / "da-1-1"),
            "--all",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    with pytest.raises(ValueError, match="mutually exclusive"):
        RubricGenerationConfig.from_namespace(args)


def test_generate_has_no_dry_run_flag() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["generate", "da-1-1", "--dry-run"])


def test_generate_default_output_is_repo_local() -> None:
    output = default_generation_dir()
    assert output.parent == PROJECT_ROOT / "runs" / "biomnibench-rubrics"
