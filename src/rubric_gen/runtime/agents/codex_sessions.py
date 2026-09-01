"""Persistent Codex SDK sessions for iterative benchmark solver turns."""

from __future__ import annotations

import json
from importlib.resources import files
import random
import shutil
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from rubric_gen.runtime.agents.adapters import AgentAdapterRegistry
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.agents.codex_events import (
    notification_event,
    trajectory_errors,
)
from rubric_gen.runtime.agents.models import AgentRunConfig, RunPaths
from rubric_gen.runtime.agents.policy import MAX_TRANSIENT_RETRIES
from rubric_gen.runtime.agents.sessions import SessionTurnResult
from rubric_gen.runtime.agents.contracts import SessionContract


_TRANSPORT_ERROR_MARKERS = (
    "connection closed",
    "connection reset",
    "connection refused",
    "failed to send request",
    "invalid json-rpc line",
    "invalid json-rpc payload",
    "list_turns is not supported yet",
    "response stream disconnected",
    "transport closed",
    "websocket connection failed",
    "websocket error",
)
_TRANSPORT_ERROR_TYPES = {
    "ConnectionError",
    "RetryLimitExceededError",
    "ServerBusyError",
    "TransportClosedError",
}


def is_codex_transport_error(error: BaseException) -> bool:
    """Return true when an exception identifies provider transport failure."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in _TRANSPORT_ERROR_TYPES:
            return True
        message = str(current).lower()
        if any(marker in message for marker in _TRANSPORT_ERROR_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


@dataclass(frozen=True)
class _StreamOutcome:
    exit_code: int
    turn_started: bool
    completed: bool
    transport_uncertain: bool
    provider_unhealthy: bool
    pre_turn_failures: tuple[str, ...]


@dataclass(frozen=True)
class _TurnStartOutcome:
    handle: Any | None
    failures: tuple[str, ...]
    provider_unhealthy: bool


@dataclass(frozen=True)
class _AttemptAssessment:
    exit_code: int
    record: dict[str, object]
    provider_health_error: str | None


class CodexProviderHealthError(RuntimeError):
    """The Codex provider transport failed before a safe result existed."""


class CodexSdkSessionDriver:
    """Keep one Codex app-server and one live thread for an assignment."""

    def __init__(
        self,
        config: AgentRunConfig | None = None,
        *,
        contract: SessionContract,
        registry: AgentAdapterRegistry | None = None,
        sdk_module: ModuleType | Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or AgentRunConfig(provider="codex")
        if self.config.executable is None and sdk_module is None:
            self.config = replace(
                self.config,
                executable=self._bundled_codex_executable(),
            )
        if self.config.provider != "codex":
            raise ValueError("CodexSdkSessionDriver requires provider `codex`")
        if not 0 <= self.config.retries <= MAX_TRANSIENT_RETRIES:
            raise ValueError(
                "Persistent-session retries must be between 0 and "
                f"{MAX_TRANSIENT_RETRIES}"
            )
        if type(self.config.model) is not str or not self.config.model.strip():
            raise ValueError("A persistent session requires an explicit model")
        self.contract = contract
        self.registry = registry or AgentAdapterRegistry()
        self.adapter = self.registry.get("codex")
        self._sdk_module_override = sdk_module
        self._sleeper = sleeper
        self._client: Any | None = None
        self._thread: Any | None = None
        self._session_id: str | None = None
        self._workspace: Path | None = None
        self._model: str | None = None
        self._closed = False

    def start(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        *,
        on_session_id: Callable[[str], None] | None = None,
    ) -> SessionTurnResult:
        if self._session_id is not None:
            raise RuntimeError("this Codex driver already owns a session")
        paths = self._prepare_turn(workspace, prompt, turn_dir)
        self._ensure_client(paths)
        assert self._client is not None
        thread = self._retry_before_turn(
            lambda: self._client.thread_start(**self._thread_options(workspace)),
            phase="thread start",
        )
        session_id = self._thread_id(thread)
        self._bind_live_thread(thread, session_id, workspace)
        if on_session_id is not None:
            on_session_id(session_id)
        return self._run_turn_attempts(paths, prompt, resumed=False)

    def resume(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult:
        if not session_id.strip():
            raise ValueError("A non-empty provider session ID is required to resume")
        paths = self._prepare_turn(workspace, prompt, turn_dir)
        self._ensure_client(paths)
        resolved_workspace = workspace.resolve()
        if self._workspace is not None and self._workspace != resolved_workspace:
            raise ValueError(
                f"Session {session_id} was started in {self._workspace}, "
                f"not {resolved_workspace}"
            )
        if self._thread is None:
            assert self._client is not None
            thread = self._retry_before_turn(
                lambda: self._client.thread_resume(
                    session_id,
                    **self._thread_options(workspace),
                ),
                phase="thread resume",
            )
            reported = self._thread_id(thread)
            if reported != session_id:
                raise RuntimeError(
                    f"Codex resumed thread {reported!r}; expected {session_id!r}"
                )
            self._bind_live_thread(thread, session_id, workspace)
        elif self._session_id != session_id:
            raise ValueError(
                f"this Codex driver owns session {self._session_id}, not {session_id}"
            )
        return self._run_turn_attempts(paths, prompt, resumed=True)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        self._thread = None
        if client is not None:
            client.close()

    def _prepare_turn(self, workspace: Path, prompt: str, turn_dir: Path) -> RunPaths:
        if self._closed:
            raise RuntimeError("the Codex session driver is closed")
        turn_dir.mkdir(parents=True, exist_ok=True)
        paths = RunPaths(
            provider="codex",
            run_dir=turn_dir,
            workspace_dir=workspace,
            prompt_path=turn_dir / "prompt.txt",
            policy_path=turn_dir / "no-web-policy.toml",
            stream_path=turn_dir / "trajectory.stream.jsonl",
            status_path=turn_dir / "status.json",
        )
        paths.prompt_path.write_text(prompt)
        self.adapter.prepare_run(paths, self.config, prompt)
        return paths

    def _ensure_client(self, paths: RunPaths) -> None:
        if self._client is not None:
            return
        executable = self._codex_executable()
        environment = self.adapter.build_environment(paths, self.config)
        sdk = self._sdk_module()
        command = (
            sys.executable,
            "-m",
            "rubric_gen.runtime.agents.codex_app_server",
            str(Path(executable).resolve()),
            str(paths.workspace_dir.resolve()),
            environment["HOME"],
            environment["TMPDIR"],
            environment["CODEX_HOME"],
        )
        sdk_config = sdk.CodexConfig(
            launch_args_override=command,
            cwd=str(paths.workspace_dir.resolve()),
        )
        self._client = self._retry_before_turn(
            lambda: sdk.Codex(sdk_config),
            phase="app-server start",
        )

    def _codex_executable(self) -> str:
        executable_name = self.adapter.executable(self.config)
        executable = shutil.which(executable_name)
        if executable is None:
            raise SystemExit(
                f"Could not find `{executable_name}` on PATH. "
                f"{self.adapter.install_hint()}"
            )
        return str(Path(executable).resolve())

    @staticmethod
    def _bundled_codex_executable() -> str:
        bundled = Path(str(files("codex_cli_bin").joinpath("bin", "codex")))
        if not bundled.is_file():
            raise RuntimeError("The Codex SDK package has no bundled CLI binary")
        return str(bundled.resolve())

    def _sdk_module(self) -> ModuleType | Any:
        if self._sdk_module_override is not None:
            return self._sdk_module_override
        try:
            import openai_codex
        except ImportError as exc:  # pragma: no cover - packaging catches this.
            raise RuntimeError(
                "Codex solver sessions require the `openai-codex` package"
            ) from exc
        return openai_codex

    def _thread_options(self, workspace: Path) -> dict[str, object]:
        sdk = self._sdk_module()
        options: dict[str, object] = {
            "approval_mode": sdk.ApprovalMode.deny_all,
            "cwd": str(workspace.resolve()),
            "model": self.config.model,
        }
        if self.config.reasoning_effort is not None:
            options["config"] = {
                "model_reasoning_effort": self.config.reasoning_effort,
            }
        if self.config.service_tier is not None:
            options["service_tier"] = self.config.service_tier
        return options

    def _retry_before_turn(self, operation: Callable[[], Any], *, phase: str) -> Any:
        failures: list[str] = []
        for retry_index in range(self.config.retries + 1):
            try:
                return operation()
            except Exception as exc:
                if not is_codex_transport_error(exc):
                    raise
                failures.append(f"{type(exc).__name__}: {exc}")
                if retry_index >= self.config.retries:
                    raise CodexProviderHealthError(
                        f"Codex {phase} failed after {len(failures)} attempts: "
                        f"{failures[-1]}"
                    ) from exc
                self._sleeper(self._retry_delay(retry_index))
        raise AssertionError("unreachable")

    @staticmethod
    def _retry_delay(retry_index: int) -> float:
        base = min(2 ** retry_index, 8)
        return base + random.uniform(0.0, base * 0.25)

    def _bind_live_thread(
        self,
        thread: Any,
        session_id: str,
        workspace: Path,
    ) -> None:
        self._thread = thread
        self._session_id = session_id
        self._workspace = workspace.resolve()
        self._model = self.config.model

    @staticmethod
    def _thread_id(thread: Any) -> str:
        value = getattr(thread, "id", None)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError("Codex SDK did not report a thread ID")
        return value

    def _run_turn_attempts(
        self,
        paths: RunPaths,
        prompt: str,
        *,
        resumed: bool,
    ) -> SessionTurnResult:
        assert self._thread is not None
        assert self._session_id is not None
        assert self._model is not None
        attempts_dir = paths.run_dir / "attempts"
        attempts_dir.mkdir()
        attempt_paths: list[Path] = []
        attempt_records: list[dict[str, object]] = []
        effective_exit_code = 1
        provider_health_error: str | None = None

        for attempt_index in range(1, self.config.retries + 2):
            attempt_prompt = self._attempt_prompt(prompt, attempt_index)
            attempt_stream = (
                attempts_dir / f"attempt-{attempt_index:03d}.trajectory.stream.jsonl"
            )
            attempt_prompt_path = attempts_dir / f"attempt-{attempt_index:03d}.prompt.txt"
            attempt_prompt_path.write_text(attempt_prompt)
            outcome = self._stream_turn(
                attempt_prompt,
                attempt_stream,
                workspace=paths.workspace_dir,
            )
            assessment = self._assess_attempt(
                outcome,
                attempt_stream=attempt_stream,
                attempt_index=attempt_index,
                attempt_prompt_path=attempt_prompt_path,
                workspace=paths.workspace_dir,
            )
            attempt_paths.append(attempt_stream)
            attempt_records.append(assessment.record)
            effective_exit_code = assessment.exit_code
            provider_health_error = (
                assessment.provider_health_error or provider_health_error
            )
            if effective_exit_code == 0:
                break
            if not self._can_recover_output(outcome, assessment.record):
                break

        with paths.stream_path.open("wb") as combined:
            for attempt_path in attempt_paths:
                combined.write(attempt_path.read_bytes())
        self._write_status(
            paths,
            effective_exit_code,
            resumed=resumed,
            attempts=attempt_records,
        )
        if provider_health_error is not None:
            raise CodexProviderHealthError(provider_health_error)
        return SessionTurnResult(
            self._session_id,
            self._model,
            effective_exit_code,
            paths.stream_path,
        )

    def _attempt_prompt(self, prompt: str, attempt_index: int) -> str:
        return prompt if attempt_index == 1 else self.contract.output_recovery_prompt

    def _assess_attempt(
        self,
        outcome: _StreamOutcome,
        *,
        attempt_stream: Path,
        attempt_index: int,
        attempt_prompt_path: Path,
        workspace: Path,
    ) -> _AttemptAssessment:
        stream_errors = trajectory_errors(attempt_stream)
        output_errors = self.contract.output_errors(workspace)
        exit_code = self._effective_exit_code(
            outcome.exit_code,
            stream_errors,
            output_errors,
        )
        record: dict[str, object] = {
            "attempt": attempt_index,
            "process_exit_code": outcome.exit_code,
            "exit_code": exit_code,
            "turn_started": outcome.turn_started,
            "turn_completed": outcome.completed,
            "pre_turn_failures": list(outcome.pre_turn_failures),
            "stream_errors": stream_errors,
            "output_errors": output_errors,
            "prompt": str(attempt_prompt_path),
            "trajectory": str(attempt_stream),
        }
        return _AttemptAssessment(
            exit_code,
            record,
            self._provider_health_error(outcome, stream_errors),
        )

    @staticmethod
    def _effective_exit_code(
        process_exit_code: int,
        stream_errors: list[str],
        output_errors: list[str],
    ) -> int:
        if process_exit_code != 0:
            return process_exit_code
        if stream_errors:
            return 1
        return 2 if output_errors else 0

    @staticmethod
    def _provider_health_error(
        outcome: _StreamOutcome,
        stream_errors: list[str],
    ) -> str | None:
        unhealthy = [
            error
            for error in stream_errors
            if is_codex_transport_error(RuntimeError(error))
        ]
        if unhealthy:
            return unhealthy[-1]
        if outcome.provider_unhealthy:
            return "Codex transport closed during an active turn"
        return None

    @staticmethod
    def _can_recover_output(
        outcome: _StreamOutcome,
        record: dict[str, object],
    ) -> bool:
        return (
            not outcome.transport_uncertain
            and outcome.exit_code == 0
            and record["stream_errors"] == []
        )

    def _stream_turn(
        self,
        prompt: str,
        stream_path: Path,
        *,
        workspace: Path,
    ) -> _StreamOutcome:
        assert self._thread is not None
        assert self._session_id is not None
        with stream_path.open("w") as log:
            self._write_event(
                log,
                {
                    "type": "thread.started",
                    "thread_id": self._session_id,
                    "model": self.config.model,
                },
            )
            started = self._start_turn(prompt, workspace, log)
            if started.handle is None:
                return _StreamOutcome(
                    1,
                    False,
                    False,
                    False,
                    started.provider_unhealthy,
                    started.failures,
                )
            handle = started.handle
            self._write_event(
                log,
                {
                    "type": "turn.started",
                    "thread_id": self._session_id,
                    "turn_id": handle.id,
                },
            )
            return self._consume_turn(handle, log, started.failures)

    def _start_turn(self, prompt: str, workspace: Path, log: Any) -> _TurnStartOutcome:
        assert self._thread is not None
        failures: list[str] = []
        for retry_index in range(self.config.retries + 1):
            try:
                handle = self._thread.turn(prompt, cwd=str(workspace.resolve()))
                return _TurnStartOutcome(handle, tuple(failures), False)
            except Exception as exc:
                description = f"{type(exc).__name__}: {exc}"
                failures.append(description)
                unhealthy = is_codex_transport_error(exc)
                if not unhealthy or retry_index >= self.config.retries:
                    self._write_event(
                        log,
                        {
                            "type": "error",
                            "phase": "turn_start",
                            "message": description,
                        },
                    )
                    return _TurnStartOutcome(None, tuple(failures), unhealthy)
                self._write_event(
                    log,
                    {
                        "type": "transport.retry",
                        "phase": "turn_start",
                        "attempt": retry_index + 1,
                        "message": description,
                    },
                )
                self._sleeper(self._retry_delay(retry_index))
        raise AssertionError("unreachable")

    def _consume_turn(
        self,
        handle: Any,
        log: Any,
        failures: tuple[str, ...],
    ) -> _StreamOutcome:
        timed_out = threading.Event()
        timer = threading.Timer(
            self.config.timeout_seconds,
            self._interrupt_turn,
            args=(timed_out,),
        )
        timer.daemon = True
        timer.start()
        completed = False
        latest_usage: dict[str, object] | None = None
        stream: Any | None = None
        try:
            stream = handle.stream()
            for notification in stream:
                assert self._session_id is not None
                event, usage = notification_event(
                    notification,
                    latest_usage,
                    session_id=self._session_id,
                )
                latest_usage = usage or latest_usage
                if event is not None:
                    self._write_event(log, event)
                    if event.get("type") == "turn.completed":
                        completed = event.get("status") == "completed"
        except Exception as exc:
            message = (
                "Codex turn timed out"
                if timed_out.is_set()
                else f"{type(exc).__name__}: {exc}"
            )
            self._write_event(
                log,
                {
                    "type": "error",
                    "phase": "turn_stream",
                    "message": message,
                },
            )
            return _StreamOutcome(
                124 if timed_out.is_set() else 1,
                True,
                False,
                True,
                not timed_out.is_set() and is_codex_transport_error(exc),
                failures,
            )
        finally:
            timer.cancel()
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        if timed_out.is_set():
            self._write_event(
                log,
                {
                    "type": "error",
                    "phase": "turn_stream",
                    "message": "Codex turn timed out",
                },
            )
            return _StreamOutcome(124, True, completed, True, False, failures)
        return _StreamOutcome(
            0 if completed else 1,
            True,
            completed,
            False,
            False,
            failures,
        )

    def _interrupt_turn(self, timed_out: threading.Event) -> None:
        timed_out.set()
        self.close()

    def _write_event(self, log: Any, event: dict[str, object]) -> None:
        line = json.dumps(event, sort_keys=True) + "\n"
        log.write(line)
        log.flush()
        if not self.config.quiet:
            self.adapter.print_line(line, raw=self.config.raw)

    def _write_status(
        self,
        paths: RunPaths,
        exit_code: int,
        *,
        resumed: bool,
        attempts: list[dict[str, object]],
    ) -> None:
        status: dict[str, object] = {
            "provider": "codex",
            "session_id": self._session_id,
            "model": self._model,
            "service_tier": self.config.service_tier,
            "resumed": resumed,
            "exit_code": exit_code,
            "workspace": str(paths.workspace_dir.resolve()),
            "trajectory": str(paths.stream_path),
            "attempt_count": len(attempts),
            "max_retries": self.config.retries,
            "timeout_seconds": self.config.timeout_seconds,
            "attempts": attempts,
            "transport_exit_code": exit_code,
        }
        status.update(
            RunCost.from_stream(
                paths.stream_path,
                model=self._model,
                service_tier=self.config.service_tier,
            ).fields()
        )
        paths.status_path.write_text(
            json.dumps(status, indent=2, sort_keys=True) + "\n"
        )
