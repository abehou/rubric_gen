"""Validated assignment identities for randomized revision studies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExperimentAssignment:
    """One immutable cell in the randomized experiment design."""

    task_id: str
    replicate: int
    solver_id: str
    condition_id: str
    within_block_order: int
    execution_order: int

    def __post_init__(self) -> None:
        for name, value in (
            ("task_id", self.task_id),
            ("solver_id", self.solver_id),
            ("condition_id", self.condition_id),
        ):
            if (
                type(value) is not str
                or not value
                or Path(value).name != value
                or value in {".", ".."}
            ):
                raise ValueError(f"{name} must be a safe non-empty basename")
        for name, value in (
            ("replicate", self.replicate),
            ("within_block_order", self.within_block_order),
            ("execution_order", self.execution_order),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def assignment_id(self) -> str:
        return (
            f"{self.task_id}--rep-{self.replicate:03d}--solver-{self.solver_id}--"
            f"{self.condition_id}"
        )

    @property
    def study_relative_path(self) -> Path:
        return (
            Path("experiments")
            / self.task_id
            / f"rep-{self.replicate:03d}"
            / self.solver_id
            / self.condition_id
        )

    def record_identity(self) -> dict[str, object]:
        return {
            "assignment_id": self.assignment_id,
            "task_id": self.task_id,
            "replicate": self.replicate,
            "solver_id": self.solver_id,
            "condition_id": self.condition_id,
            "execution_order": self.execution_order,
            "experiment_dir": self.study_relative_path.as_posix(),
        }
