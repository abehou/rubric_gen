from __future__ import annotations

import pytest

from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.vllm import (
    normalize_vllm_base_url,
    parse_vllm_endpoints,
)


def test_cli_exposes_only_core_workflow() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    assert set(subparsers.choices) == {"run", "seed", "revise", "detect", "judge"}


@pytest.mark.parametrize(
    "argv",
    [
        ["revise", "--experiment", "experiment.yaml", "--dry-run"],
        ["detect", "--run-dir", "r", "--output-dir", "o", "--preflight-only"],
    ],
)
def test_cli_rejects_non_executing_modes(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


@pytest.mark.parametrize("command", ["seed", "revise", "run"])
def test_experiment_commands_accept_repeatable_vllm_endpoints(command: str) -> None:
    args = build_parser().parse_args([
        command,
        "--experiment", "experiment.yaml",
        "--vllm", "http://qwen27:43117::Qwen/Qwen3.6-27B",
        "--vllm", "http://qwen35:43583/v1::Qwen/Qwen3.6-35B-A3B",
    ])
    assert parse_vllm_endpoints(args.vllm) == {
        "Qwen/Qwen3.6-27B": "http://qwen27:43117/v1",
        "Qwen/Qwen3.6-35B-A3B": "http://qwen35:43583/v1",
    }


def test_detect_and_judge_accept_vllm_endpoints() -> None:
    detect = build_parser().parse_args([
        "detect", "--run-dir", "runs/study", "--output-dir", "runs/detect",
        "--vllm", "http://qwen27:43117::Qwen/Qwen3.6-27B",
    ])
    judge = build_parser().parse_args([
        "judge", "--run-dir", "runs/revision", "--output-dir", "runs/judge",
        "--vllm", "http://qwen27:43117::Qwen/Qwen3.6-27B",
        "--vllm", "http://qwen35:43583::Qwen/Qwen3.6-35B-A3B",
    ])
    assert detect.vllm == ["http://qwen27:43117::Qwen/Qwen3.6-27B"]
    assert len(judge.vllm) == 2
    assert judge.models is None


def test_judge_rejects_mixed_hosted_and_vllm_model_sources() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "judge", "--run-dir", "r", "--output-dir", "o",
            "--models", "gpt-5.6-sol",
            "--vllm", "http://qwen27:43117::Qwen/Qwen3.6-27B",
        ])


def test_vllm_endpoint_parser_is_strict() -> None:
    assert normalize_vllm_base_url("https://node:8000/") == "https://node:8000/v1"
    with pytest.raises(ValueError, match="URL::MODEL"):
        parse_vllm_endpoints(["http://node:8000/Qwen/Test"])
    with pytest.raises(ValueError, match="duplicate"):
        parse_vllm_endpoints([
            "http://one:8000::Qwen/Test",
            "http://two:8000::Qwen/Test",
        ])
    with pytest.raises(ValueError, match="base URL"):
        parse_vllm_endpoints(["node:8000::Qwen/Test"])
