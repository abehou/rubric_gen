from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.forensics.reward_hacking import (
    PANEL,
    RewardHackingAuditConfig,
    RewardHackingAuditRunner,
    forensic_audit_prompt,
)


class _FakeAdapter:
    default_executable = "sh"

    def prepare_run(
        self,
        paths: RunPaths,
        config: AgentRunConfig,
        prompt: str,
    ) -> None:
        paths.prompt_path.write_text(prompt, encoding="utf-8")

    def build_command(
        self,
        paths: RunPaths,
        config: AgentRunConfig,
        prompt: str,
    ) -> list[str]:
        return [
            "sh", "-c",
            "printf '%s' \"$AUDIT_REPORT\" > audit.md; "
            "printf '%s' '{\"decision\":\"no_reward_hacking_detected\",\"confidence\":0.8,\"evidence_locations\":[]}' > verdict.json",
            "sh",
        ]


class _FakeRegistry:
    def __init__(self) -> None:
        self.adapter = _FakeAdapter()

    def get(self, provider: str) -> _FakeAdapter:
        return self.adapter


def _experiment(tmp_path: Path) -> tuple[Path, Path]:
    tasks = tmp_path / "tasks"
    task = tasks / "da-1-1"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("Original task\n", encoding="utf-8")
    experiment = tmp_path / "revision-example"
    experiment.mkdir()
    (experiment / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "rubric-gen-submission-revision-experiment",
                "task_id": "da-1-1",
            }
        ),
        encoding="utf-8",
    )
    return tasks, experiment


def test_prompt_is_open_ended_and_task_first(tmp_path: Path) -> None:
    tasks, experiment = _experiment(tmp_path)
    prompt = forensic_audit_prompt(
        task_id="da-1-1",
        task_dir=tasks / "da-1-1",
        experiment_dir=experiment,
    )

    assert "Do not assume a predefined set or taxonomy" in prompt
    assert "Read the original task before the rubric" in prompt
    assert "actively search for disconfirming evidence" in prompt
    assert "Ignore every opinion" in prompt


def test_config_flattens_repeated_run_dir_arguments(tmp_path: Path) -> None:
    tasks, first = _experiment(tmp_path)
    second = tmp_path / "revision-second"
    args = argparse.Namespace(
        run_dir=[[str(first)], [str(second)]],
        output_dir=str(tmp_path / "out"),
        tasks_dir=str(tasks),
        max_concurrency=2,
        resume=True,
        dry_run=False,
        raw=False,
    )

    config = RewardHackingAuditConfig.from_namespace(args)

    assert config.experiment_dirs == (first, second)
    assert config.max_concurrency == 2
    assert config.resume is True


def test_dry_run_plans_all_panel_members(
    tmp_path: Path, capsys
) -> None:
    tasks, experiment = _experiment(tmp_path)
    config = RewardHackingAuditConfig(
        experiment_dirs=(experiment,),
        output_dir=tmp_path / "out",
        tasks_dir=tasks,
        dry_run=True,
    )

    runner = RewardHackingAuditRunner(
        config, registry=_FakeRegistry()  # type: ignore[arg-type]
    )
    assert runner.run() == 0
    output = capsys.readouterr().out
    assert "3 forensic panel member run(s)" in output
    for provider, model in PANEL:
        assert f"{provider}\t{model}" in output
    assert not config.output_dir.exists()


def test_judge_agent_ensemble_is_mutually_exclusive_with_score_ensemble() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["judge", "--agent-ensemble", "--run-dir", "revision-example"]
    )

    assert args.agent_ensemble is True
    assert args.ensemble is False
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "judge",
                "--ensemble",
                "--agent-ensemble",
                "--run-dir",
                "revision-example",
            ]
        )


def test_case_dir_requires_agent_ensemble_at_execution(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["judge", "--case-dir", str(tmp_path)])
    from rubric_gen.biomnibench.commands import run_judge

    with pytest.raises(ValueError, match="only with --agent-ensemble"):
        run_judge(args)


def test_case_manifest_rejects_gold_leakage(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "kind": "reward-hacking-forensic-case",
        "case_id": "opaque",
        "labels": ["leak"],
        "evidence_files": ["transcript.json"],
    }))
    config = RewardHackingAuditConfig(
        experiment_dirs=(), case_dirs=(case,), output_dir=tmp_path / "out",
        tasks_dir=tmp_path, dry_run=True,
    )
    with pytest.raises(ValueError, match="leaks gold"):
        RewardHackingAuditRunner(config, registry=_FakeRegistry()).run()  # type: ignore[arg-type]


def test_runner_preserves_three_independent_reports(
    tmp_path: Path, monkeypatch
) -> None:
    tasks, experiment = _experiment(tmp_path)
    output = tmp_path / "out"
    config = RewardHackingAuditConfig(
        experiment_dirs=(experiment,),
        output_dir=output,
        tasks_dir=tasks,
    )
    monkeypatch.setenv(
        "AUDIT_REPORT",
        "# Independent audit\n\n" + "Evidence-backed open-ended finding. " * 30,
    )

    exit_code = RewardHackingAuditRunner(
        config, registry=_FakeRegistry()  # type: ignore[arg-type]
    ).run()

    assert exit_code == 0
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert len(summary["records"]) == len(PANEL) == 3
    assert {record["provider"] for record in summary["records"]} == {
        "codex",
        "claude",
        "gemini",
    }
    panel = (
        output / "experiments" / experiment.name / "panel.md"
    ).read_text(encoding="utf-8")
    assert "reduced by majority vote" in panel
    for provider, model in PANEL:
        assert f"## {provider} — {model}" in panel
