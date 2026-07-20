from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.sessions import (
    OUTPUT_RECOVERY_PROMPT,
    RECOVERY_PROMPT,
    CliSolverSessionDriver,
)


class ScriptedSessionDriver(CliSolverSessionDriver):
    def __init__(self, outcomes: list[str], *, retries: int = 5) -> None:
        super().__init__(
            AgentRunConfig(
                provider="gemini",
                model="gemini-test",
                quiet=True,
                retries=retries,
            )
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
        command[command.index("-p") + 1] == RECOVERY_PROMPT
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


def test_persistent_session_accepts_workspace_after_five_stream_retries(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    turn_dir = tmp_path / "turn"
    driver = ScriptedSessionDriver(["error"] * 6)

    result = driver.start(workspace, "original prompt", turn_dir)

    assert result.exit_code == 0
    assert len(driver.commands) == 6
    status = json.loads((turn_dir / "status.json").read_text())
    assert status["attempt_count"] == 6
    assert status["max_retries"] == 5
    assert status["exit_code"] == 0
    assert status["transport_exit_code"] == 1
    assert status["accepted_after_retry_exhaustion"] is True
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
    assert status["accepted_after_retry_exhaustion"] is False


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
        OUTPUT_RECOVERY_PROMPT
    )
    status = json.loads((turn_dir / "status.json").read_text())
    assert status["attempts"][0]["output_errors"] == [
        "missing_or_invalid: trace.md",
        "missing_or_invalid: answer.txt",
    ]
    assert status["attempts"][1]["output_errors"] == []
