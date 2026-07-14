"""Persistent CLI sessions for iterative BiomniBench solver turns."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

from rubric_gen.biomnibench.adapters import AgentAdapterRegistry
from rubric_gen.biomnibench.common import NO_WEB_POLICY, AgentRunConfig, RunPaths


@dataclass(frozen=True)
class SessionTurnResult:
    session_id: str
    exit_code: int
    trajectory_path: Path


class SolverSessionDriver(Protocol):
    def start(self, workspace: Path, prompt: str, turn_dir: Path) -> SessionTurnResult: ...

    def resume(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult: ...


class CliSolverSessionDriver:
    """Run one solver conversation across multiple provider CLI invocations."""

    def __init__(
        self,
        config: AgentRunConfig | None = None,
        *,
        registry: AgentAdapterRegistry | None = None,
    ) -> None:
        self.config = config or AgentRunConfig()
        if self.config.extra_args:
            raise ValueError("extra_args are not allowed for a persistent session")
        if self.config.retries != 1:
            raise ValueError(
                "A persistent session requires retries=1 because replay is unsafe"
            )
        self.registry = registry or AgentAdapterRegistry()
        self.adapter = self.registry.get(self.config.provider)
        self._session_workspaces: dict[str, Path] = {}

    def start(self, workspace: Path, prompt: str, turn_dir: Path) -> SessionTurnResult:
        self._ensure_executable()
        paths = self._prepare_turn(workspace, prompt, turn_dir)

        requested_session_id = (
            str(uuid.uuid4()) if self.adapter.name in {"gemini", "claude"} else None
        )

        command = self._build_command(
            paths,
            prompt,
            session_id=requested_session_id or "",
            resume=False,
        )
        exit_code = self._stream(command, paths)
        session_id = self._attest_session_id(
            paths,
            exit_code,
            expected=requested_session_id,
            resumed=False,
        )

        self._bind_workspace(session_id, workspace)
        self._write_status(paths, exit_code, session_id=session_id, resumed=False)
        return SessionTurnResult(session_id, exit_code, paths.stream_path)

    def resume(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult:
        if not session_id.strip():
            raise ValueError("A non-empty provider session ID is required to resume")

        self._ensure_executable()
        self._bind_workspace(session_id, workspace)
        paths = self._prepare_turn(workspace, prompt, turn_dir)
        command = self._build_command(paths, prompt, session_id=session_id, resume=True)
        exit_code = self._stream(command, paths)
        reported_session_id = self._attest_session_id(
            paths,
            exit_code,
            expected=session_id,
            resumed=True,
        )
        self._write_status(
            paths,
            exit_code,
            session_id=reported_session_id,
            resumed=True,
        )
        return SessionTurnResult(reported_session_id, exit_code, paths.stream_path)

    def _ensure_executable(self) -> None:
        executable = self.adapter.executable(self.config)
        if shutil.which(executable) is None:
            raise SystemExit(
                f"Could not find `{executable}` on PATH. {self.adapter.install_hint()}"
            )

    def _prepare_turn(self, workspace: Path, prompt: str, turn_dir: Path) -> RunPaths:
        turn_dir.mkdir(parents=True, exist_ok=True)
        policy_path = (
            workspace.parent / "no-web-policy.toml"
            if self.adapter.name == "gemini"
            else turn_dir / "no-web-policy.toml"
        )
        paths = RunPaths(
            provider=self.adapter.name,
            run_dir=turn_dir,
            workspace_dir=workspace,
            prompt_path=turn_dir / "prompt.txt",
            policy_path=policy_path,
            stream_path=turn_dir / "trajectory.stream.jsonl",
            status_path=turn_dir / "status.json",
        )
        paths.prompt_path.write_text(prompt)
        if self.adapter.name == "gemini":
            self._ensure_gemini_policy(paths.policy_path)
        return paths

    @staticmethod
    def _ensure_gemini_policy(policy_path: Path) -> None:
        if policy_path.is_symlink():
            raise RuntimeError("Gemini no-web policy must not be a symbolic link")
        if policy_path.exists():
            mode = policy_path.stat().st_mode
            if not policy_path.is_file() or policy_path.read_text() != NO_WEB_POLICY:
                raise RuntimeError("Existing Gemini no-web policy does not match")
            if mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                raise RuntimeError("Existing Gemini no-web policy is writable")
            return
        policy_path.write_text(NO_WEB_POLICY)
        policy_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    def _build_command(
        self,
        paths: RunPaths,
        prompt: str,
        *,
        session_id: str,
        resume: bool,
    ) -> list[str]:
        provider = self.adapter.name

        if provider == "codex":
            command = [self.adapter.executable(self.config), "exec"]
            if resume:
                command.append("resume")
            command.extend(
                [
                    "-c",
                    f"approval_policy={json.dumps(self.config.approval_mode or 'never')}",
                    "-c",
                    'sandbox_mode="workspace-write"',
                    "-c",
                    (
                        'web_search="live"'
                        if self.config.allow_web
                        else 'web_search="disabled"'
                    ),
                    "--skip-git-repo-check",
                    "--json",
                ]
            )
            if self.config.model:
                command.extend(["--model", self.config.model])
            if self.config.skip_trust:
                command.append("--dangerously-bypass-hook-trust")
            if resume:
                command.append(session_id)
            command.append(prompt)
            return command

        # Start from the ordinary adapter command so provider-native model,
        # permission, no-web, sandbox, and trust behavior stays aligned.
        command = self.adapter.build_command(paths, self.config)

        if provider == "gemini":
            prompt_index = command.index("-p") + 1
            command[prompt_index] = prompt
            command.extend(["--resume" if resume else "--session-id", session_id])
            return command

        if provider == "claude":
            command.remove("--no-session-persistence")
            command[-1] = prompt
            command[-1:-1] = ["--resume" if resume else "--session-id", session_id]
            return command

        raise RuntimeError(f"Session continuation is unsupported for provider `{provider}`")

    def _stream(self, command: list[str], paths: RunPaths) -> int:
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        workspace = paths.workspace_dir.resolve()
        env["PWD"] = str(workspace)
        env.pop("OLDPWD", None)
        with paths.stream_path.open("w") as log:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert process.stdout is not None
            self._tee_stream(process.stdout, log)
            return process.wait()

    def _tee_stream(self, stdout: TextIO, log: TextIO) -> None:
        for line in stdout:
            log.write(line)
            log.flush()
            if not self.config.quiet:
                self.adapter.print_line(line, raw=self.config.raw)

    def _attest_session_id(
        self,
        paths: RunPaths,
        exit_code: int,
        *,
        expected: str | None,
        resumed: bool,
    ) -> str:
        reported = self._reported_session_id(paths.stream_path)
        phase = "resume" if resumed else "start"
        if not reported:
            self._write_status(paths, exit_code, session_id=None, resumed=resumed)
            raise RuntimeError(
                f"{self.adapter.name} did not report a session ID during {phase}"
            )
        if expected is not None and reported != expected:
            self._write_status(
                paths,
                exit_code,
                session_id=reported,
                resumed=resumed,
            )
            raise RuntimeError(
                f"{self.adapter.name} reported session ID {reported!r} during {phase}; "
                f"expected {expected!r}"
            )
        return reported

    def _reported_session_id(self, stream_path: Path) -> str:
        if self.adapter.name == "codex":
            return self._codex_session_id(stream_path)
        for line in stream_path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if self.adapter.name == "gemini":
                is_session_event = event.get("type") == "init"
            else:
                is_session_event = (
                    event.get("type") == "system" and event.get("subtype") == "init"
                )
            if not is_session_event:
                continue
            value = event.get("session_id")
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _bind_workspace(self, session_id: str, workspace: Path) -> None:
        resolved = workspace.resolve()
        previous = self._session_workspaces.setdefault(session_id, resolved)
        if previous != resolved:
            raise ValueError(
                f"Session {session_id} was started in {previous}, not {resolved}"
            )

    def _write_status(
        self,
        paths: RunPaths,
        exit_code: int,
        *,
        session_id: str | None,
        resumed: bool,
    ) -> None:
        paths.status_path.write_text(
            json.dumps(
                {
                    "provider": self.adapter.name,
                    "session_id": session_id,
                    "resumed": resumed,
                    "exit_code": exit_code,
                    "workspace": str(paths.workspace_dir.resolve()),
                    "trajectory": str(paths.stream_path),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    @staticmethod
    def _codex_session_id(stream_path: Path) -> str:
        for line in stream_path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") not in {
                "thread.started",
                "session.started",
                "conversation.started",
            }:
                continue
            for key in ("thread_id", "session_id", "conversation_id"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            thread = event.get("thread")
            if isinstance(thread, dict):
                value = thread.get("id")
                if isinstance(value, str) and value.strip():
                    return value
        return ""
