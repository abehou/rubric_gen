from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Callable

import rubric_gen.runtime.agents.adapters as adapters_module
import rubric_gen.runtime.agents.runners as runners_module
import rubric_gen.runtime.agents.sessions as sessions_module
from rubric_gen.runtime.agents.models import AgentRunConfig, RunPaths
from rubric_gen.runtime.agents.adapters import CodexAdapter, VllmAdapter
from rubric_gen.runtime.agents.runners import AgentRunner
from rubric_gen.runtime.agents.sessions import (
    CliSolverSessionDriver,
)
from rubric_gen.benchmarks.biomnibench_da.contract import (
    BIOMNIBENCH_DA,
    BIOMNIBENCH_DA_PROMPT,
    BIOMNIBENCH_DA_OUTPUT_RECOVERY_PROMPT,
    BIOMNIBENCH_DA_RECOVERY_PROMPT,
)


def _run_paths(tmp_path: Path) -> RunPaths:
    workspace = tmp_path / "workspace"
    run_dir = tmp_path / "run"
    workspace.mkdir()
    run_dir.mkdir()
    return RunPaths(
        provider="codex",
        run_dir=run_dir,
        workspace_dir=workspace,
        prompt_path=run_dir / "prompt.txt",
        policy_path=run_dir / "policy.toml",
        stream_path=run_dir / "stream.jsonl",
        status_path=run_dir / "status.json",
    )


def test_one_shot_codex_agent_reads_explicit_prompt_stdin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _run_paths(tmp_path)
    runner = AgentRunner(
        AgentRunConfig(
            provider="codex",
            model="test-model",
            quiet=True,
        ),
        prompt=BIOMNIBENCH_DA_PROMPT,
        output_errors=BIOMNIBENCH_DA.output_errors,
    )
    monkeypatch.setattr(
        runner.adapter,
        "prepare_run",
        lambda paths, _config, prompt: paths.prompt_path.write_text(prompt),
    )
    monkeypatch.setattr(
        runner,
        "build_command",
        lambda _: [sys.executable, "-c", "print('done')"],
    )
    original_popen = runners_module.subprocess.Popen
    popen_kwargs: list[dict[str, object]] = []

    def recording_popen(*args, **kwargs):
        popen_kwargs.append(kwargs)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(runners_module.subprocess, "Popen", recording_popen)

    assert runner.stream(paths) == 0
    assert popen_kwargs[0]["stdin"].name == str(paths.prompt_path)
    assert paths.stream_path.read_text() == "done\n"


def test_persistent_codex_agent_reads_explicit_prompt_stdin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _run_paths(tmp_path)
    paths.prompt_path.write_text("prompt from file")
    driver = CliSolverSessionDriver(
        AgentRunConfig(
            provider="codex",
            model="test-model",
            quiet=True,
        ),
        contract=BIOMNIBENCH_DA,
    )
    original_popen = sessions_module.subprocess.Popen
    popen_kwargs: list[dict[str, object]] = []

    def recording_popen(*args, **kwargs):
        popen_kwargs.append(kwargs)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(sessions_module.subprocess, "Popen", recording_popen)

    assert driver._stream(
        [sys.executable, "-c", "print('done')"],
        paths,
    ) == 0
    assert popen_kwargs[0]["stdin"].name == str(paths.prompt_path)
    assert paths.stream_path.read_text() == "done\n"


def test_persistent_codex_agent_streams_prompt_larger_than_argument_limit(
    tmp_path: Path,
) -> None:
    paths = _run_paths(tmp_path)
    prompt = "x" * 145_155
    paths.prompt_path.write_text(prompt)
    driver = CliSolverSessionDriver(
        AgentRunConfig(
            provider="codex",
            model="test-model",
            quiet=True,
        ),
        contract=BIOMNIBENCH_DA,
    )

    assert driver._stream(
        [
            sys.executable,
            "-c",
            "import sys; print(len(sys.stdin.buffer.read()))",
        ],
        paths,
    ) == 0
    assert paths.stream_path.read_text() == "145155\n"


class ScriptedSessionDriver(CliSolverSessionDriver):
    def __init__(self, outcomes: list[str], *, retries: int = 5) -> None:
        super().__init__(
            AgentRunConfig(
                provider="gemini",
                model="gemini-test",
                quiet=True,
                retries=retries,
            ),
            contract=BIOMNIBENCH_DA,
        )
        self.outcomes = outcomes
        self.commands: list[list[str]] = []

    def _ensure_executable(self) -> None:
        return None

    def _stream(
        self,
        command: list[str],
        paths: RunPaths,
        *,
        on_session_id: Callable[[str], None] | None = None,
    ) -> int:
        self.commands.append(command)
        flag = "--resume" if "--resume" in command else "--session-id"
        session_id = command[command.index(flag) + 1]
        if on_session_id is not None:
            on_session_id(session_id)
        outcome = self.outcomes[len(self.commands) - 1]
        events: list[dict[str, object]] = [
            {
                "type": "init",
                "session_id": session_id,
                "model": "gemini-test",
            }
        ]
        if outcome in {"error", "process_error"}:
            events.extend(
                [
                    {
                        "type": "tool_use",
                        "tool_name": "write_file",
                        "parameters": {"file_path": "suspicious.py"},
                    },
                    {"type": "error", "message": "Invalid stream"},
                    {"type": "result", "status": "error"},
                ]
            )
        else:
            events.extend(
                [
                    {
                        "type": "tool_use",
                        "tool_name": "write_file",
                        "parameters": {"file_path": "suspicious.py"},
                    },
                    {"type": "result", "status": "success"},
                ]
            )
            if outcome == "success":
                (paths.workspace_dir / "trace.md").write_text("trace\n")
                (paths.workspace_dir / "answer.txt").write_text("answer\n")
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text(
            "".join(json.dumps(event) + "\n" for event in events)
        )
        return 9 if outcome == "process_error" else 0


def test_codex_persistent_session_has_no_network_or_web_override(
    tmp_path: Path,
) -> None:
    driver = CliSolverSessionDriver(
        AgentRunConfig(
            provider="codex",
            model="gpt-5.6-luna",
        ),
        contract=BIOMNIBENCH_DA,
    )
    paths = RunPaths.for_task(
        task_dir=tmp_path / "task",
        runs_dir=tmp_path / "runs",
        provider="codex",
    )

    command = driver._build_command(
        paths, "prompt", session_id="session-id", resume=False
    )

    assert "--strict-config" in command
    assert "--ignore-rules" in command
    assert "--search" not in command
    assert command[-1] == "-"
    assert "prompt" not in command
    assert not hasattr(driver.config, "allow_network")

    resumed = driver._build_command(
        paths, "follow-up", session_id="session-id", resume=True
    )
    assert resumed[-2:] == ["session-id", "-"]
    assert "follow-up" not in resumed


def test_agent_environment_uses_workspace_local_temporary_directory(
    tmp_path: Path,
) -> None:
    paths = _run_paths(tmp_path)

    environment = CodexAdapter().build_environment(
        paths,
        AgentRunConfig(provider="codex", model="gpt-5.6-luna"),
    )

    temporary = paths.workspace_dir / ".agent-tmp"
    assert environment["TMPDIR"] == str(temporary)
    assert temporary.is_dir()
    assert temporary.stat().st_mode & 0o777 == 0o700
    (temporary / "command.out").write_text("ok\n")


def test_codex_adapter_restores_controlled_config_between_turns(tmp_path: Path) -> None:
    paths = RunPaths(
        provider="codex",
        run_dir=tmp_path / "turn",
        workspace_dir=tmp_path / "workspace",
        prompt_path=tmp_path / "turn" / "prompt.txt",
        policy_path=tmp_path / "turn" / "policy.toml",
        stream_path=tmp_path / "turn" / "stream.jsonl",
        status_path=tmp_path / "turn" / "status.json",
    )
    config = AgentRunConfig(provider="codex", model="gpt-5.6-luna")
    adapter = CodexAdapter()
    adapter.prepare_run(paths, config, "first")
    controlled = tmp_path / ".agent-state" / "codex" / "config.toml"
    expected = controlled.read_text()
    controlled.write_text(expected + "\n# normalized by CLI\n")

    adapter.prepare_run(paths, config, "second")

    assert controlled.read_text() == expected


def test_codex_adapter_mounts_its_sandbox_helpers_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_root = tmp_path / "npm" / "@openai" / "codex"
    launcher = package_root / "bin" / "codex.js"
    native = (
        package_root
        / "node_modules"
        / "@openai"
        / "codex-linux-x64"
        / "vendor"
        / "x86_64-unknown-linux-musl"
        / "bin"
        / "codex"
    )
    bundled_rg = native.parent.parent / "codex-path" / "rg"
    for path in (launcher, native, bundled_rg):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("executable")
        path.chmod(0o755)
    monkeypatch.setattr(adapters_module.shutil, "which", lambda _: str(launcher))

    paths = RunPaths(
        provider="codex",
        run_dir=tmp_path / "turn",
        workspace_dir=tmp_path / "workspace",
        prompt_path=tmp_path / "turn" / "prompt.txt",
        policy_path=tmp_path / "turn" / "policy.toml",
        stream_path=tmp_path / "turn" / "stream.jsonl",
        status_path=tmp_path / "turn" / "status.json",
    )
    CodexAdapter().prepare_run(
        paths,
        AgentRunConfig(provider="codex", model="gpt-5.6-luna"),
        "Solve the task.",
    )

    controlled = tmp_path / ".agent-state" / "codex" / "config.toml"
    filesystem = tomllib.loads(controlled.read_text())["permissions"][
        "benchmark-task"
    ]["filesystem"]
    assert filesystem[str(native)] == "read"
    assert filesystem[str(bundled_rg)] == "read"
    assert filesystem[":minimal"] == "read"
    assert filesystem[":workspace_roots"] == {".": "write"}


def test_codex_adapter_requests_schema_constrained_final_output(tmp_path: Path) -> None:
    paths = RunPaths(
        provider="codex",
        run_dir=tmp_path / "turn",
        workspace_dir=tmp_path / "workspace",
        prompt_path=tmp_path / "turn" / "prompt.txt",
        policy_path=tmp_path / "turn" / "policy.toml",
        stream_path=tmp_path / "turn" / "stream.jsonl",
        status_path=tmp_path / "turn" / "status.json",
        output_schema_path=tmp_path / "workspace" / "data" / "schema.json",
        output_last_message_path=tmp_path / "workspace" / "answer.txt",
    )

    command = CodexAdapter().build_command(
        paths,
        AgentRunConfig(provider="codex", model="gpt-5.6-luna"),
        "propose",
    )

    assert command[command.index("--output-schema") + 1] == str(
        paths.output_schema_path.resolve()
    )
    assert command[command.index("--output-last-message") + 1] == str(
        paths.output_last_message_path.resolve()
    )
    assert command[-1] == "-"
    assert "propose" not in command


def test_vllm_adapter_uses_codex_responses_without_hosted_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODEX_API_KEY", "must-not-leak")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    paths = RunPaths(
        provider="vllm",
        run_dir=tmp_path / "turn",
        workspace_dir=tmp_path / "workspace",
        prompt_path=tmp_path / "turn" / "prompt.txt",
        policy_path=tmp_path / "turn" / "policy.toml",
        stream_path=tmp_path / "turn" / "stream.jsonl",
        status_path=tmp_path / "turn" / "status.json",
    )
    config = AgentRunConfig(
        provider="vllm",
        model="Qwen/Qwen3.6-27B",
        base_url="http://qwen27:43117/v1",
        timeout_seconds=123,
    )
    adapter = VllmAdapter()
    paths.workspace_dir.mkdir()

    adapter.prepare_run(paths, config, "solve")

    controlled = (
        tmp_path / ".agent-state" / "vllm-codex" / "config.toml"
    ).read_text()
    assert 'model_provider = "vllm"' in controlled
    assert "model_context_window = 262144" in controlled
    assert 'base_url = "http://qwen27:43117/v1"' in controlled
    assert 'wire_api = "responses"' in controlled
    assert "stream_idle_timeout_ms = 123000" in controlled
    command = adapter.build_command(paths, config, "solve")
    assert command[-1] == "-"
    assert "solve" not in command
    assert command[command.index("--model") + 1] == "Qwen/Qwen3.6-27B"
    environment = adapter.build_environment(paths, config)
    assert "CODEX_API_KEY" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert environment["CODEX_HOME"].endswith("/.agent-state/vllm-codex")


def test_persistent_session_retries_in_same_session_and_preserves_all_streams(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    turn_dir = tmp_path / "turn"
    driver = ScriptedSessionDriver(["error", "error", "success"])

    result = driver.start(workspace, "original prompt", turn_dir)

    assert result.exit_code == 0
    assert len(driver.commands) == 3
    assert "--session-id" in driver.commands[0]
    assert all("--resume" in command for command in driver.commands[1:])
    assert driver.commands[0][driver.commands[0].index("-p") + 1] == ("original prompt")
    assert all(
        command[command.index("-p") + 1] == BIOMNIBENCH_DA_RECOVERY_PROMPT
        for command in driver.commands[1:]
    )

    attempts = turn_dir / "attempts"
    assert sorted(path.name for path in attempts.glob("*.trajectory.stream.jsonl")) == [
        "attempt-001.trajectory.stream.jsonl",
        "attempt-002.trajectory.stream.jsonl",
        "attempt-003.trajectory.stream.jsonl",
    ]
    canonical = (turn_dir / "trajectory.stream.jsonl").read_text()
    assert canonical.count('"tool_name": "write_file"') == 3
    assert canonical.count('"message": "Invalid stream"') == 2
    assert canonical.rstrip().endswith('"status": "success"}')

    status = json.loads((turn_dir / "status.json").read_text())
    assert status["attempt_count"] == 3
    assert status["max_retries"] == 5
    assert status["exit_code"] == 0
    assert status["attempts"][0]["stream_errors"] == [
        "trajectory_error: Invalid stream",
        "trajectory_result_status: error",
    ]
    assert status["attempts"][2]["stream_errors"] == []


def test_persistent_session_fails_after_five_stream_retries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    turn_dir = tmp_path / "turn"
    driver = ScriptedSessionDriver(["error"] * 6)

    result = driver.start(workspace, "original prompt", turn_dir)

    assert result.exit_code == 1
    assert len(driver.commands) == 6
    status = json.loads((turn_dir / "status.json").read_text())
    assert status["attempt_count"] == 6
    assert status["max_retries"] == 5
    assert status["exit_code"] == 1
    assert status["transport_exit_code"] == 1
    assert "accepted_after_retry_exhaustion" not in status
    assert (turn_dir / "trajectory.stream.jsonl").read_text().count(
        '"message": "Invalid stream"'
    ) == 6


def test_persistent_session_does_not_accept_process_crashes_after_retries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    turn_dir = tmp_path / "turn"
    driver = ScriptedSessionDriver(["process_error"] * 6)

    result = driver.start(workspace, "original prompt", turn_dir)

    assert result.exit_code == 9
    status = json.loads((turn_dir / "status.json").read_text())
    assert status["exit_code"] == 9
    assert status["transport_exit_code"] == 9
    assert "accepted_after_retry_exhaustion" not in status


def test_persistent_session_does_not_reject_suspicious_successful_actions(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    driver = ScriptedSessionDriver(["success"])

    result = driver.start(workspace, "original prompt", tmp_path / "turn")

    assert result.exit_code == 0
    assert len(driver.commands) == 1


def test_persistent_session_recovers_when_success_omits_required_outputs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    turn_dir = tmp_path / "turn"
    driver = ScriptedSessionDriver(["incomplete", "success"])

    result = driver.start(workspace, "original prompt", turn_dir)

    assert result.exit_code == 0
    assert len(driver.commands) == 2
    assert "--resume" in driver.commands[1]
    assert driver.commands[1][driver.commands[1].index("-p") + 1] == (
        BIOMNIBENCH_DA_OUTPUT_RECOVERY_PROMPT
    )
    status = json.loads((turn_dir / "status.json").read_text())
    assert status["attempts"][0]["output_errors"] == [
        "missing_or_invalid: trace.md",
        "missing_or_invalid: answer.txt",
    ]
    assert status["attempts"][1]["output_errors"] == []
