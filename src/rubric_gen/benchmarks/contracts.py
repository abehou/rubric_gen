"""Native task and submission contracts for revision benchmarks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.benchmarks import Benchmark


@dataclass(frozen=True)
class FinalEvidence:
    """One native final-submission artifact exposed to an outcome audit."""

    name: str
    artifact: str
    content: str


class SubmissionBenchmark(ABC):
    """Define native inputs, outputs, and prompts for one benchmark."""

    benchmark: Benchmark
    initial_prompt: str
    recovery_prompt: str
    output_recovery_prompt: str
    revision_action: str
    required_outputs: tuple[str, ...]
    retained_workspace_names: frozenset[str]
    answer_artifact: str | None = None
    required_review: str | None = None

    def validate_experiment(self, tasks_dir: Path, task_ids: tuple[str, ...]) -> None:
        """Validate the benchmark dataset and all selected task inputs."""

        self.validate_dataset(tasks_dir, task_ids)
        for task_id in task_ids:
            self.validate_task(tasks_dir / task_id)

    def validate_dataset(self, tasks_dir: Path, task_ids: tuple[str, ...]) -> None:
        """Validate dataset-level provenance when the benchmark has it."""

    def validate_task(self, task_dir: Path) -> None:
        """Validate the common task layout plus benchmark-specific files."""

        for path in self.required_task_paths(task_dir):
            if path.is_symlink() or not path.exists():
                raise ValueError(f"task input is missing or symlinked: {path}")

    def required_task_paths(self, task_dir: Path) -> tuple[Path, ...]:
        """Return the immutable inputs required by one task."""

        return (
            task_dir / "instruction.md",
            task_dir / "environment" / "data",
            task_dir / "tests" / "rubric.txt",
        )

    def validate_review(self, review: object) -> None:
        """Reject a review mode that cannot represent the native submission."""

        if self.required_review is not None and review != self.required_review:
            raise ValueError(
                f"{self.benchmark.value} requires {self.required_review} review"
            )

    def render_workspace_review(self, task_dir: Path, workspace: Path) -> str:
        """Render a benchmark-native workspace review for a judge."""

        raise ValueError(
            f"{self.benchmark.value} does not support workspace review"
        )

    @abstractmethod
    def output_errors(self, workspace: Path) -> list[str]:
        """Return errors in the benchmark's native deliverables."""

    @abstractmethod
    def render_submission(self, workspace: Path) -> str:
        """Render the native submission for a rubric proposer or judge."""

    @abstractmethod
    def final_evidence(self, workspace: Path) -> tuple[FinalEvidence, ...]:
        """Return native final artifacts for blinded outcome auditing."""
