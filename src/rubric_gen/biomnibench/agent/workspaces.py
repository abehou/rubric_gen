"""Task discovery and solver workspace preparation."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path


class TaskWorkspace:
    def __init__(self, task_dir: Path, workspace_dir: Path) -> None:
        self.task_dir = task_dir
        self.workspace_dir = workspace_dir

    @property
    def instruction_path(self) -> Path:
        return self.task_dir / "instruction.md"

    @property
    def data_dir(self) -> Path:
        return self.task_dir / "environment" / "data"

    def validate(self) -> None:
        try:
            instruction_stat = os.lstat(self.instruction_path)
        except OSError:
            raise SystemExit(f"Missing instruction.md in {self.task_dir}")
        if not stat.S_ISREG(instruction_stat.st_mode):
            raise SystemExit(f"instruction.md is not a regular file in {self.task_dir}")
        try:
            data_stat = os.lstat(self.data_dir)
        except OSError:
            raise SystemExit(f"Missing environment/data in {self.task_dir}")
        if not stat.S_ISDIR(data_stat.st_mode):
            raise SystemExit(f"environment/data is not a regular directory in {self.task_dir}")
        for path in self.data_dir.rglob("*"):
            mode = os.lstat(path).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise SystemExit(f"Task data contains a non-regular entry: {path}")

    def create(self) -> None:
        self.validate()
        if os.path.lexists(self.workspace_dir):
            raise FileExistsError(f"workspace already exists: {self.workspace_dir}")
        self.workspace_dir.mkdir(parents=True)
        shutil.copy2(self.instruction_path, self.workspace_dir / "instruction.md")
        shutil.copytree(self.data_dir, self.workspace_dir / "data")

    def restore_inputs(self) -> None:
        """Restore canonical inputs into an existing solution-only workspace."""
        self.validate()
        if self.workspace_dir.is_symlink() or not self.workspace_dir.is_dir():
            raise RuntimeError(f"invalid restore workspace: {self.workspace_dir}")
        for destination in (
            self.workspace_dir / "instruction.md",
            self.workspace_dir / "data",
        ):
            if os.path.lexists(destination):
                raise RuntimeError(f"restore input already exists: {destination}")
        shutil.copy2(self.instruction_path, self.workspace_dir / "instruction.md")
        shutil.copytree(self.data_dir, self.workspace_dir / "data")


class TaskCatalog:
    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir

    def tasks(self) -> list[Path]:
        if not self.tasks_dir.is_dir():
            raise SystemExit(f"Missing tasks directory: {self.tasks_dir}")
        return sorted(
            task_dir
            for task_dir in self.tasks_dir.iterdir()
            if not task_dir.is_symlink()
            and task_dir.is_dir()
            and task_dir.name.startswith("da-")
            and not (task_dir / "instruction.md").is_symlink()
            and (task_dir / "instruction.md").is_file()
            and not (task_dir / "environment" / "data").is_symlink()
            and (task_dir / "environment" / "data").is_dir()
        )


class CompletedRunIndex:
    def __init__(self, runs_dir: Path, provider: str) -> None:
        self.runs_dir = runs_dir
        self.provider = provider

    def find(self, task_name: str) -> Path | None:
        for run_dir in sorted(
            self.runs_dir.glob(f"{task_name}-{self.provider}-*"), reverse=True
        ):
            if self.is_completed(run_dir, self.provider):
                return run_dir
        return None

    @staticmethod
    def is_completed(run_dir: Path, provider: str) -> bool:
        status_path = run_dir / "status.json"
        if not status_path.is_file():
            return False
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return False
        if status.get("provider") not in (None, provider):
            return False

        workspace_dir = Path(status.get("workspace_dir") or run_dir / "workspace")
        trace_path = workspace_dir / "trace.md"
        answer_path = workspace_dir / "answer.txt"
        return (
            status.get("exit_code") == 0
            and not status.get("validation_errors")
            and trace_path.is_file()
            and answer_path.is_file()
            and trace_path.stat().st_size > 0
            and answer_path.stat().st_size > 0
        )
