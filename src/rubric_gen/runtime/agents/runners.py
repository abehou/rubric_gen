"""Execution runners for benchmark agent experiments."""

from __future__ import annotations

import json
import os
import re
import signal
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from rubric_gen.runtime.agents.adapters import AgentAdapterRegistry
from rubric_gen.runtime.agents.contracts import OutputValidator
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.agents.models import AgentRunConfig, RunPaths
from rubric_gen.runtime.agents.workspaces import (
    TaskWorkspace,
    ensure_artifacts_dir,
)


@dataclass(frozen=True)
class RunValidation:
    errors: tuple[str, ...] = field(default_factory=tuple)
    suspicious_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def has_transient_stream_error(self) -> bool:
        return any(
            error.startswith("trajectory_error:")
            or error.startswith("trajectory_result_status:")
            for error in self.errors
        )

    def effective_exit_code(self, process_exit_code: int) -> int:
        if process_exit_code != 0:
            return process_exit_code
        return 0 if self.ok else 1

    def fields(self) -> dict[str, list[str] | bool]:
        return {
            "validation_ok": self.ok,
            "validation_errors": list(self.errors),
            "suspicious_files": list(self.suspicious_files),
        }

    @classmethod
    def from_status(cls, status_path: Path) -> "RunValidation | None":
        if not status_path.is_file():
            return None
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return None
        if "validation_errors" not in status and "suspicious_files" not in status:
            return None
        return cls(
            errors=tuple(status.get("validation_errors") or ()),
            suspicious_files=tuple(status.get("suspicious_files") or ()),
        )


class AgentRunner:
    def __init__(
        self,
        config: AgentRunConfig | None = None,
        *,
        registry: AgentAdapterRegistry | None = None,
        prompt: str,
        output_errors: OutputValidator,
    ) -> None:
        if not prompt.strip():
            raise ValueError("agent prompt must not be empty")
        if not callable(output_errors):
            raise TypeError("agent output validator must be callable")
        self.config = config or AgentRunConfig()
        self.registry = registry or AgentAdapterRegistry()
        self.adapter = self.registry.get(self.config.provider)
        self.prompt = prompt
        self.output_errors = output_errors

    @property
    def provider(self) -> str:
        return self.adapter.name

    def ensure_executable(self) -> None:
        executable = self.adapter.executable(self.config)
        if shutil.which(executable) is None:
            raise SystemExit(
                f"Could not find `{executable}` on PATH. {self.adapter.install_hint()}"
            )

    def build_command(self, paths: RunPaths) -> list[str]:
        return self.adapter.build_command(paths, self.config, self.prompt)

    def stream(self, paths: RunPaths) -> int:
        self.adapter.prepare_run(paths, self.config, self.prompt)
        command = self.build_command(paths)
        env = self.adapter.build_environment(paths, self.config)

        if not self.config.quiet:
            print(f"Provider: {self.provider}")
            print(f"Run dir: {paths.run_dir}")
            print(f"Workspace: {paths.workspace_dir}")
            print(f"Trajectory log: {paths.stream_path}")
            print("Starting agent CLI...\n", flush=True)

        with (
            paths.prompt_path.open() as prompt_input,
            paths.stream_path.open("w") as log,
        ):
            proc = subprocess.Popen(
                command,
                cwd=paths.workspace_dir,
                env=env,
                text=True,
                stdin=(
                    prompt_input
                    if self.adapter.prompt_via_stdin
                    else subprocess.DEVNULL
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                start_new_session=os.name == "posix",
            )
            timed_out = threading.Event()

            def terminate_on_timeout() -> None:
                timed_out.set()
                self._terminate_process(proc)

            timer = threading.Timer(self.config.timeout_seconds, terminate_on_timeout)
            timer.daemon = True
            timer.start()
            try:
                assert proc.stdout is not None
                self._tee_stream(proc.stdout, log)
                exit_code = proc.wait()
                return 124 if timed_out.is_set() else exit_code
            finally:
                timer.cancel()
                if proc.poll() is None:
                    self._terminate_process(proc)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:  # pragma: no cover
                process.terminate()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # pragma: no cover
                    process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def _tee_stream(self, stdout: TextIO, log: TextIO) -> None:
        for line in stdout:
            log.write(line)
            log.flush()
            if not self.config.quiet:
                self.adapter.print_line(line, raw=self.config.raw)

    def validate_outputs(self, paths: RunPaths) -> RunValidation:
        errors = self.output_errors(paths.workspace_dir)
        errors.extend(self.trajectory_errors(paths.stream_path))
        suspicious_files = self.find_cross_run_references(paths)
        return RunValidation(tuple(errors), tuple(suspicious_files))

    def trajectory_errors(self, stream_path: Path) -> list[str]:
        if not stream_path.is_file():
            return []

        errors = []
        with stream_path.open() as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                status = event.get("status")
                if event_type == "error":
                    message = event.get("message") or event.get("error") or "unknown"
                    errors.append(f"trajectory_error: {message}")
                if event_type == "result" and status not in (
                    None,
                    "success",
                    "completed",
                ):
                    errors.append(f"trajectory_result_status: {status}")
        return errors

    def find_cross_run_references(self, paths: RunPaths) -> list[str]:
        suspicious = []
        for text_path in self.workspace_text_files(paths.workspace_dir):
            try:
                content = text_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if self.has_cross_run_reference(content, paths):
                suspicious.append(str(text_path.relative_to(paths.workspace_dir)))
        return suspicious

    def workspace_text_files(self, workspace_dir: Path) -> list[Path]:
        suffixes = {".py", ".r", ".R", ".sh", ".md", ".txt", ".json", ".jsonl", ".toml"}
        files = []
        for path in workspace_dir.rglob("*"):
            if not path.is_file():
                continue
            if any(
                name in path.parts for name in (".agent-tmp", ".venv", "data")
            ):
                continue
            if path.suffix in suffixes:
                files.append(path)
        return files

    def has_cross_run_reference(self, content: str, paths: RunPaths) -> bool:
        runs_root = self.runs_root(paths)
        allowed_prefixes = {
            str(paths.run_dir.resolve()),
            str(paths.run_dir),
            str(paths.workspace_dir.resolve()),
            str(paths.workspace_dir),
        }
        if paths.run_dir.parent.name == "tasks":
            allowed_prefixes.add(str(paths.run_dir.parents[1].resolve()))
            allowed_prefixes.add(str(paths.run_dir.parents[1]))

        for root in {str(runs_root.resolve()), str(runs_root)}:
            root_pattern = re.escape(root)
            path_pattern = re.compile(rf"{root_pattern}(?:[^\s\"'`),;\]]*)?")
            for match in path_pattern.finditer(content):
                referenced = match.group(0).rstrip(".")
                if any(referenced.startswith(prefix) for prefix in allowed_prefixes):
                    continue
                return True
        return False

    def runs_root(self, paths: RunPaths) -> Path:
        if paths.run_dir.parent.name == "tasks":
            return paths.run_dir.parents[2]
        return paths.run_dir.parent

    def run(
        self,
        task_dir: Path,
        runs_dir: Path | None = None,
        *,
        paths: RunPaths | None = None,
    ) -> tuple[int, RunPaths]:
        self.ensure_executable()
        if paths is None:
            if runs_dir is None:
                raise ValueError("runs_dir is required when paths is not provided")
            paths = RunPaths.for_task(task_dir, runs_dir, provider=self.provider)
        paths.run_dir.mkdir(parents=True, exist_ok=True)
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        ensure_artifacts_dir(paths.workspace_dir)

        attempts = []
        max_attempts = self.config.retries + 1
        for attempt in range(1, max_attempts + 1):
            process_exit_code = self.stream(paths)
            validation = self.validate_outputs(paths)
            exit_code = validation.effective_exit_code(process_exit_code)
            attempt_record = {
                "attempt": attempt,
                "process_exit_code": process_exit_code,
                "exit_code": exit_code,
                **validation.fields(),
            }
            attempts.append(attempt_record)
            if exit_code == 0 or not self.should_retry(
                attempt, max_attempts, validation
            ):
                break
            self.archive_attempt(paths, attempt, attempt_record)
            self._recreate_workspace(task_dir, paths.workspace_dir)

        cost = RunCost.from_stream(
            paths.stream_path,
            model=self.config.model,
            service_tier=self.config.service_tier,
        )
        status = {
            "provider": self.provider,
            "requested_model": self.config.model,
            "task": task_dir.name,
            "task_dir": str(task_dir),
            "workspace_dir": str(paths.workspace_dir),
            "attempt_count": len(attempts),
            "max_retries": self.config.retries,
            "timeout_seconds": self.config.timeout_seconds,
            "service_tier": self.config.service_tier,
            "attempts": attempts,
            "process_exit_code": process_exit_code,
            "exit_code": exit_code,
            **validation.fields(),
            **cost.fields(),
        }
        paths.status_path.write_text(json.dumps(status, indent=2) + "\n")
        return exit_code, paths

    @staticmethod
    def _recreate_workspace(task_dir: Path, workspace: Path) -> None:
        if workspace.is_symlink() or not workspace.is_dir():
            raise RuntimeError(f"retry workspace is invalid: {workspace}")
        shutil.rmtree(workspace)
        TaskWorkspace(task_dir, workspace).create()
        ensure_artifacts_dir(workspace)

    def should_retry(
        self,
        attempt: int,
        max_attempts: int,
        validation: RunValidation,
    ) -> bool:
        return attempt < max_attempts and validation.has_transient_stream_error

    def archive_attempt(
        self,
        paths: RunPaths,
        attempt: int,
        attempt_record: dict[str, Any],
    ) -> None:
        attempts_dir = paths.run_dir / "attempts"
        attempts_dir.mkdir(parents=True, exist_ok=True)
        if paths.stream_path.is_file():
            shutil.copy2(
                paths.stream_path,
                attempts_dir / f"attempt-{attempt}.trajectory.stream.jsonl",
            )
        for filename in ("trace.md", "answer.txt"):
            output_path = paths.workspace_dir / filename
            if output_path.is_file():
                shutil.copy2(
                    output_path, attempts_dir / f"attempt-{attempt}.{filename}"
                )
        (attempts_dir / f"attempt-{attempt}.status.json").write_text(
            json.dumps(attempt_record, indent=2) + "\n"
        )
