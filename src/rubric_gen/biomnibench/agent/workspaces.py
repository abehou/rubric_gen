"""Task discovery and solver workspace preparation."""

from __future__ import annotations

import json
import shutil
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
        if not self.instruction_path.is_file():
            raise SystemExit(f"Missing instruction.md in {self.task_dir}")
        if not self.data_dir.is_dir():
            raise SystemExit(f"Missing environment/data in {self.task_dir}")

    def prepare(self) -> None:
        self.validate()
        (self.workspace_dir / "data").mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.instruction_path, self.workspace_dir / "instruction.md")
        shutil.copytree(self.data_dir, self.workspace_dir / "data", dirs_exist_ok=True)


class TaskCatalog:
    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir

    def tasks(self) -> list[Path]:
        if not self.tasks_dir.is_dir():
            raise SystemExit(f"Missing tasks directory: {self.tasks_dir}")
        return sorted(
            task_dir
            for task_dir in self.tasks_dir.iterdir()
            if task_dir.is_dir()
            and task_dir.name.startswith("da-")
            and (task_dir / "instruction.md").is_file()
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
