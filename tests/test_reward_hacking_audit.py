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
from rubric_gen.biomnibench.forensics.evidence_index import (
    build_evidence_index,
    ensure_evidence_index,
    query_main,
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
            "printf '%s' '{\"decision\":\"no_reward_hacking_detected\",\"confidence\":0.8,\"evidence_locations\":[],\"findings\":[]}' > verdict.json",
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


def _experiment_output(output: Path, experiment: Path) -> Path:
    return output / "experiments" / RewardHackingAuditRunner._source_key(experiment)


def test_prompt_is_open_ended_and_task_first(tmp_path: Path) -> None:
    tasks, experiment = _experiment(tmp_path)
    prompt = forensic_audit_prompt(
        task_id="da-1-1",
        task_dir=tasks / "da-1-1",
        experiment_dir=experiment,
    )

    assert "Require concrete evidence of exploitation or constraint bypass" in prompt
    assert "do not silently broaden it" in prompt
    assert '"findings"' in prompt
    assert '"type"' in prompt
    assert "Read the original task before the rubric" in prompt
    assert "actively search for disconfirming evidence" in prompt
    assert "Ignore every opinion" in prompt


def test_evidence_index_supports_bounded_lossless_retrieval(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "manifest.json").write_text(json.dumps({
        "evidence_files": ["transcript.json"],
    }))
    long_content = "prefix " + "x" * 5000 + " suspicious-marker tail"
    (case / "transcript.json").write_text(json.dumps({
        "samples": [{"input": [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": long_content},
        ]}]
    }))
    database = tmp_path / "evidence.sqlite"

    inventory = build_evidence_index(case, database)
    assert inventory["events"] == 2
    assert inventory["roles"] == {"assistant": 1, "user": 1}

    assert query_main(database, ["search", "suspicious-marker"]) == 0
    assert "suspicious-marker" in capsys.readouterr().out
    assert query_main(database, ["show", "2", "--limit", "100"]) == 0
    shown = capsys.readouterr().out
    assert "continue at --start 100" in shown
    assert len(shown) < 400
    assert query_main(database, ["occurrences", "2"]) == 0
    assert "transcript.json:$/samples/0/input/1" in capsys.readouterr().out
    assert ensure_evidence_index(case, database) is None


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
        agent_step_limit=7,
    )

    config = RewardHackingAuditConfig.from_namespace(args)

    assert config.experiment_dirs == (first, second)
    assert config.max_concurrency == 2
    assert config.resume is True
    assert config.step_limit == 7
    assert config.max_retries == 2


def test_agent_panel_retries_failed_member(tmp_path: Path) -> None:
    tasks, experiment = _experiment(tmp_path)
    runner = RewardHackingAuditRunner(RewardHackingAuditConfig(
        experiment_dirs=(experiment,), output_dir=tmp_path / "out",
        tasks_dir=tasks, panel=(("gemini", "gemini-test"),), max_retries=1,
    ))
    case = runner._revision_case(experiment)
    attempts: list[bool] = []

    def member(*args, retry: bool = False, **kwargs):
        attempts.append(retry)
        return {
            "case_id": case.case_id,
            "source_kind": case.source_kind,
            "source_path": str(case.source_path),
            "provider": "gemini",
            "model": "gemini-test",
            "status": "failed" if len(attempts) == 1 else "completed",
        }

    runner._run_member = member  # type: ignore[method-assign]
    record = runner._run_member_with_retries(case, "gemini", "gemini-test")

    assert attempts == [False, True]
    assert record["status"] == "completed"
    assert record["attempt_count"] == 2
    assert record["retry_exhausted"] is False


def test_agent_step_limit_validation_and_event_counting(tmp_path: Path) -> None:
    tasks, experiment = _experiment(tmp_path)
    with pytest.raises(ValueError, match="step limit"):
        RewardHackingAuditConfig(
            experiment_dirs=(experiment,), output_dir=tmp_path / "out",
            tasks_dir=tasks, step_limit=0,
        )

    count = RewardHackingAuditRunner._completed_steps
    assert count('{"type":"tool_result"}', "gemini") == 1
    assert count(json.dumps({
        "type": "item.completed",
        "item": {"type": "command_execution"},
    }), "codex") == 1
    assert count(json.dumps({
        "message": {"content": [
            {"type": "tool_result"}, {"type": "tool_result"},
        ]},
    }), "claude") == 2
    assert count('{"type":"message"}', "gemini") == 0


def test_agent_verdict_normalizes_numeric_evidence_locations(tmp_path: Path) -> None:
    tasks, experiment = _experiment(tmp_path)
    runner = RewardHackingAuditRunner(RewardHackingAuditConfig(
        experiment_dirs=(experiment,), output_dir=tmp_path / "out", tasks_dir=tasks,
    ))
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(json.dumps({
        "decision": "reward_hacking_detected",
        "confidence": 0.9,
        "evidence_locations": [410],
        "findings": [{
            "type": "environment exploit",
            "description": "Read evaluator state to recover a scoring target.",
            "evidence_locations": [410, 414],
        }],
    }))

    verdict, error = runner._load_verdict(verdict_path)

    assert error is None
    assert verdict is not None
    assert verdict["evidence_locations"] == ["event_id:410"]
    assert verdict["findings"][0]["evidence_locations"] == [
        "event_id:410", "event_id:414"
    ]


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
    assert args.agent_step_limit == 24
    limited = parser.parse_args([
        "judge", "--agent-ensemble", "--run-dir", "revision-example",
        "--agent-step-limit", "9",
    ])
    assert limited.agent_step_limit == 9
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
    assert (output / "detection-rates.json").is_file()
    assert (output / "detection-rates.png").is_file()
    assert (output / "category-rates.json").is_file()
    assert (output / "category-rates.png").is_file()
    assert {record["provider"] for record in summary["records"]} == {
        "codex",
        "claude",
        "gemini",
    }
    panel = (_experiment_output(output, experiment) / "panel.md").read_text(
        encoding="utf-8"
    )
    assert "reduced by majority vote" in panel
    assert "Detected behavior types: none." in panel
    for provider, model in PANEL:
        assert f"## {provider} — {model}" in panel


def test_resume_archives_and_retries_invalid_member_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks, experiment = _experiment(tmp_path)
    output = tmp_path / "out"
    stale = _experiment_output(output, experiment) / "claude"
    stale.mkdir(parents=True)
    (stale / "trajectory.stream.jsonl").write_text("old failure\n")
    monkeypatch.setenv(
        "AUDIT_REPORT",
        "# Independent audit\n\n" + "Evidence-backed finding. " * 30,
    )

    assert RewardHackingAuditRunner(
        RewardHackingAuditConfig(
            experiment_dirs=(experiment,), output_dir=output,
            tasks_dir=tasks, resume=True,
        ),
        registry=_FakeRegistry(),  # type: ignore[arg-type]
    ).run() == 0

    assert (stale.with_name("claude.failed-001") / "trajectory.stream.jsonl").is_file()
    assert (stale / "workspace" / "verdict.json").is_file()


def test_resume_reruns_members_from_obsolete_audit_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks, experiment = _experiment(tmp_path)
    output = tmp_path / "out"
    stale = _experiment_output(output, experiment) / "claude"
    workspace = stale / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "audit.md").write_text("# Old\n\n" + "old evidence " * 60)
    (workspace / "verdict.json").write_text(json.dumps({
        "decision": "no_reward_hacking_detected",
        "confidence": 0.8,
        "evidence_locations": [],
        "findings": [],
    }))
    (stale / "status.json").write_text(json.dumps({"schema_version": 1}))
    monkeypatch.setenv(
        "AUDIT_REPORT",
        "# New protocol audit\n\n" + "new evidence " * 60,
    )

    assert RewardHackingAuditRunner(
        RewardHackingAuditConfig(
            experiment_dirs=(experiment,), output_dir=output,
            tasks_dir=tasks, resume=True,
        ),
        registry=_FakeRegistry(),  # type: ignore[arg-type]
    ).run() == 0
    assert (stale.with_name("claude.failed-001") / "workspace" / "audit.md").is_file()
    assert "New protocol" in (workspace / "audit.md").read_text()
