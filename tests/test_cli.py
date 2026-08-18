from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import rubric_gen.cli as unified_cli
from rubric_gen.cli import build_parser
from rubric_gen.runtime.vllm import (
    normalize_vllm_base_url,
    parse_vllm_endpoints,
)


def test_cli_exposes_only_core_workflow() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    assert set(subparsers.choices) == {
        "run", "seed", "paraphrase", "revise", "detect", "judge"
    }


@pytest.mark.parametrize(
    "argv",
    [
        ["revise", "--experiment", "experiment.yaml", "--dry-run"],
        ["detect", "--experiment", "experiment.yaml", "--preflight-only"],
    ],
)
def test_cli_rejects_non_executing_modes(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_run_dispatches_harvey_experiment(tmp_path, monkeypatch) -> None:
    path = tmp_path / "harvey.yaml"
    path.write_text(
        json.dumps(
            {"kind": "rubric-gen-harvey-harness-evolution-experiment"}
        ),
        encoding="utf-8",
    )
    experiment = SimpleNamespace(output_dir=tmp_path / "output")
    observed: dict[str, object] = {}

    class FakeController:
        def __init__(self, value: object) -> None:
            observed["experiment"] = value

        def run(self, *, resume: bool) -> int:
            observed["resume"] = resume
            observed.setdefault("stages", []).append("evolution")
            return 0

    def quality(value: object) -> int:
        assert value is experiment
        observed.setdefault("stages", []).append("quality")
        return 0

    def detect(value: object, *, resume: bool) -> int:
        assert value is experiment
        assert resume is False
        observed.setdefault("stages", []).append("detect")
        return 0

    monkeypatch.setattr(unified_cli, "load_harvey_experiment", lambda _: experiment)
    monkeypatch.setattr(unified_cli, "HarveyEvolutionController", FakeController)
    monkeypatch.setattr(unified_cli, "run_quality_audit", quality)
    monkeypatch.setattr(unified_cli, "run_reward_hacking_audit", detect)

    assert unified_cli.main(["run", "--experiment", str(path), "--resume"]) == 0
    assert observed == {
        "experiment": experiment,
        "resume": True,
        "stages": ["evolution", "quality", "detect"],
    }


def test_detect_forwards_the_experiment_to_detection_suite(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "submission.yaml"
    path.write_text(
        json.dumps({"kind": "rubric-gen-randomized-experiment"}),
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def detect(args) -> int:
        observed.update(vars(args))
        return 19

    monkeypatch.setattr(unified_cli, "run_submission_detect", detect)

    assert unified_cli.main(["detect", "--experiment", str(path)]) == 19
    assert observed["experiment"] == str(path)
    assert observed["max_concurrency"] == 3


def test_cli_experiment_routing_rejects_duplicate_yaml_keys(tmp_path) -> None:
    path = tmp_path / "experiment.yaml"
    path.write_text(
        "kind: rubric-gen-randomized-experiment\n"
        "kind: rubric-gen-randomized-experiment\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate YAML key: kind"):
        unified_cli.main(["detect", "--experiment", str(path)])


def test_run_accepts_restart() -> None:
    args = build_parser().parse_args([
        "run",
        "--experiment",
        "experiment.yaml",
        "--restart",
    ])

    assert args.restart is True
    assert args.resume is False


def test_run_rejects_restart_with_resume() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "run",
            "--experiment",
            "experiment.yaml",
            "--restart",
            "--resume",
        ])


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


def test_detect_accepts_vllm_endpoints() -> None:
    detect = build_parser().parse_args([
        "detect", "--experiment", "experiment.yaml",
        "--vllm", "http://qwen27:43117::Qwen/Qwen3.6-27B",
    ])
    assert detect.vllm == ["http://qwen27:43117::Qwen/Qwen3.6-27B"]


def test_judge_accepts_only_the_strong_original_rubric_workflow() -> None:
    judge = build_parser().parse_args([
        "judge",
        "--experiment", "experiment.yaml",
        "--output-dir", "runs/judge",
        "--max-concurrency", "2",
        "--max-retries", "0",
        "--resume",
    ])
    assert judge.experiment == "experiment.yaml"
    assert judge.output_dir == "runs/judge"
    assert judge.max_concurrency == 2
    assert judge.max_retries == 0
    assert judge.resume is True
    assert not hasattr(judge, "models")
    assert not hasattr(judge, "vllm")


@pytest.mark.parametrize(
    "legacy_args",
    [
        ["--run-dir", "runs/revision"],
        ["--study-dir", "runs/study"],
        ["--models", "gpt-5.6-sol"],
        ["--vllm", "http://qwen27:43117::Qwen/Qwen3.6-27B"],
    ],
)
def test_judge_rejects_removed_interfaces(legacy_args: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "judge",
            "--experiment", "experiment.yaml",
            "--output-dir", "runs/judge",
            *legacy_args,
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
