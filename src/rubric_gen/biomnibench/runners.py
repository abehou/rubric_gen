"""Execution runners for BiomniBench agent experiments."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from rubric_gen.biomnibench.adapters import AgentAdapterRegistry
from rubric_gen.biomnibench.common import (
    AgentRunConfig,
    BatchRunPaths,
    BatchRunConfig,
    CompletedRunIndex,
    RunCost,
    RunPaths,
    TaskCatalog,
    TaskWorkspace,
    TerminalProgress,
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
    ) -> None:
        self.config = config or AgentRunConfig()
        self.registry = registry or AgentAdapterRegistry()
        self.adapter = self.registry.get(self.config.provider)

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
        return self.adapter.build_command(paths, self.config)

    def stream(self, paths: RunPaths) -> int:
        self.adapter.prepare_run(paths, self.config)
        command = self.build_command(paths)
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")

        if not self.config.quiet:
            print(f"Provider: {self.provider}")
            print(f"Run dir: {paths.run_dir}")
            print(f"Workspace: {paths.workspace_dir}")
            print(f"Trajectory log: {paths.stream_path}")
            print("Starting agent CLI...\n", flush=True)

        with paths.stream_path.open("w") as log:
            proc = subprocess.Popen(
                command,
                cwd=paths.workspace_dir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert proc.stdout is not None
            self._tee_stream(proc.stdout, log)
            return proc.wait()

    def _tee_stream(self, stdout: TextIO, log: TextIO) -> None:
        for line in stdout:
            log.write(line)
            log.flush()
            if not self.config.quiet:
                self.adapter.print_line(line, raw=self.config.raw)

    def validate_outputs(self, paths: RunPaths) -> RunValidation:
        errors = []
        for filename in ("trace.md", "answer.txt"):
            output_path = paths.workspace_dir / filename
            if not output_path.is_file() or output_path.stat().st_size == 0:
                errors.append(f"missing_or_empty: {filename}")

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
            if ".venv" in path.parts or "data" in path.parts:
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
        TaskWorkspace(task_dir, paths.workspace_dir).prepare()

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

        cost = RunCost.from_stream(paths.stream_path)
        status = {
            "provider": self.provider,
            "task": task_dir.name,
            "task_dir": str(task_dir),
            "workspace_dir": str(paths.workspace_dir),
            "attempt_count": len(attempts),
            "max_retries": self.config.retries,
            "attempts": attempts,
            "process_exit_code": process_exit_code,
            "exit_code": exit_code,
            **validation.fields(),
            **cost.fields(),
        }
        paths.status_path.write_text(json.dumps(status, indent=2) + "\n")
        return exit_code, paths

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


class BiomniBenchBatchRunner:
    def __init__(
        self,
        config: BatchRunConfig,
        *,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self.config = config
        self.agent_runner = agent_runner or AgentRunner(config.agent_config())
        self.batch_paths = self._make_batch_paths()

    @property
    def summary_path(self) -> Path:
        return self.batch_paths.summary_path

    def _make_batch_paths(self) -> BatchRunPaths:
        if self.config.resume_run is not None:
            return BatchRunPaths.resume(self.config.resume_run, self.config.provider)
        return BatchRunPaths.create(self.config.runs_dir, self.config.provider)

    def discover_tasks(self) -> list[Path]:
        return TaskCatalog(self.config.tasks_dir).tasks()

    def completed_run(self, task_name: str) -> Path | None:
        task_paths = self.batch_paths.task_paths(Path(task_name))
        if CompletedRunIndex.is_completed(task_paths.run_dir, self.config.provider):
            return task_paths.run_dir
        return None

    def skipped_record(self, task_dir: Path, completed: Path) -> dict[str, str]:
        cost = RunCost.for_run_dir(completed)
        return {
            "provider": self.config.provider,
            "task": task_dir.name,
            "status": "skipped",
            "reason": "completed",
            "run_dir": str(completed),
            **cost.fields(),
        }

    def result_record(
        self,
        task_dir: Path,
        exit_code: int,
        paths: RunPaths,
        validation: RunValidation | None = None,
    ) -> dict[str, str | int]:
        cost = RunCost.from_stream(paths.stream_path)
        status = self.read_status(paths.status_path)
        validation = validation or RunValidation.from_status(paths.status_path)
        validation = validation or self.agent_runner.validate_outputs(paths)
        process_exit_code = status.get("process_exit_code", exit_code)
        effective_exit_code = status.get(
            "exit_code", validation.effective_exit_code(process_exit_code)
        )
        return {
            "provider": self.config.provider,
            "task": task_dir.name,
            "status": "completed" if effective_exit_code == 0 else "failed",
            "process_exit_code": process_exit_code,
            "exit_code": effective_exit_code,
            "attempt_count": status.get("attempt_count"),
            "max_retries": status.get("max_retries"),
            **validation.fields(),
            **cost.fields(),
            "run_dir": str(paths.run_dir),
            "workspace_dir": str(paths.workspace_dir),
            "trace": str(paths.workspace_dir / "trace.md"),
            "answer": str(paths.workspace_dir / "answer.txt"),
            "trajectory": str(paths.stream_path),
        }

    def read_status(self, status_path: Path) -> dict[str, Any]:
        if not status_path.is_file():
            return {}
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return {}
        return status if isinstance(status, dict) else {}

    def write_summary(self, summary: TextIO, record: dict[str, Any]) -> None:
        summary.write(json.dumps(record) + "\n")
        summary.flush()

    def run(self) -> int:
        tasks = self.discover_tasks()
        self.batch_paths.batch_dir.mkdir(parents=True, exist_ok=True)
        self.batch_paths.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.batch_paths.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.batch_paths.status_path.write_text(
            json.dumps(
                {
                    "provider": self.config.provider,
                    "tasks_dir": str(self.config.tasks_dir),
                    "runs_dir": str(self.config.runs_dir),
                    "batch_dir": str(self.batch_paths.batch_dir),
                    "resumed": self.batch_paths.is_resume,
                    "total_tasks": len(tasks),
                    "max_concurrency": self.config.max_concurrency,
                },
                indent=2,
            )
            + "\n"
        )

        attempted = 0
        overall_exit = 0
        runnable: list[tuple[int, Path]] = []
        with (
            self.summary_path.open("a") as summary,
            BatchProgress(
                self.batch_paths,
                total=len(tasks),
            ) as progress,
        ):
            for index, task_dir in enumerate(tasks, start=1):
                completed = None
                if not self.config.force:
                    completed = self.completed_run(task_dir.name)
                if completed is not None:
                    record = self.skipped_record(task_dir, completed)
                    self.write_summary(summary, record)
                    progress.record(index, task_dir.name, "skipped", record)
                    progress.update()
                    continue

                if self.config.limit is not None and attempted >= self.config.limit:
                    progress.record(
                        index,
                        task_dir.name,
                        "limit_reached",
                        {"limit": self.config.limit},
                    )
                    break

                attempted += 1
                runnable.append((index, task_dir))

            if self.config.max_concurrency == 1 or len(runnable) <= 1:
                for index, task_dir in runnable:
                    progress.record(index, task_dir.name, "started", {"attempt": index})
                    exit_code, _task_dir, _paths, record = self.run_task(task_dir)
                    self.write_summary(summary, record)
                    progress.record(index, task_dir.name, str(record["status"]), record)
                    progress.update()

                    if exit_code != 0:
                        overall_exit = exit_code
                        if not self.config.continue_on_error:
                            break
            else:
                with ThreadPoolExecutor(
                    max_workers=self.config.max_concurrency
                ) as executor:
                    futures = {
                        executor.submit(self.run_task, task_dir): (index, task_dir)
                        for index, task_dir in runnable
                    }
                    for future in as_completed(futures):
                        index, task_dir = futures[future]
                        exit_code, _task_dir, _paths, record = future.result()
                        self.write_summary(summary, record)
                        progress.record(
                            index, task_dir.name, str(record["status"]), record
                        )
                        progress.update()
                        if exit_code != 0:
                            overall_exit = exit_code

        return overall_exit

    def run_task(self, task_dir: Path) -> tuple[int, Path, RunPaths, dict[str, Any]]:
        task_paths = self.batch_paths.task_paths(task_dir)
        exit_code, paths = self.agent_runner.run(
            task_dir=task_dir.resolve(),
            paths=task_paths,
        )
        record = self.result_record(task_dir, exit_code, paths)
        return exit_code, task_dir, paths, record


class BatchProgress(TerminalProgress):
    def __init__(self, paths: BatchRunPaths, *, total: int) -> None:
        super().__init__(
            total=total,
            description=f"{paths.provider} tasks",
            unit="task",
        )
        self.paths = paths
        self._log: TextIO | None = None

    def __enter__(self) -> "BatchProgress":
        self.paths.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.paths.progress_path.open("a")
        super().__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        super().__exit__(exc_type, exc, traceback)
        if self._log is not None:
            self._log.close()

    def record(
        self,
        index: int,
        task: str,
        event: str,
        payload: dict[str, Any],
    ) -> None:
        record = {
            "index": index,
            "total": self.total,
            "provider": self.paths.provider,
            "task": task,
            "event": event,
            **payload,
        }
        if self._log is not None:
            self._log.write(json.dumps(record) + "\n")
            self._log.flush()
        self.set_status(f"{task}: {event}")
