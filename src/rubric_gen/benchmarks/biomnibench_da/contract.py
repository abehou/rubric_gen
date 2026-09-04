"""BioNMIbench-DA task and submission contract."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from rubric_gen.benchmarks.base import (
    FinalEvidence,
    SubmissionBenchmark,
    SubmissionBenchmarkId,
)


_EXPERIMENT_ENVIRONMENT = """## Experiment environment

The task data files are under `./data` in this workspace.
Treat `/app/trace.md` and `/app/answer.txt` in the task instruction as
`./trace.md` and `./answer.txt`.
Keep `./data` unchanged.
Network access and package installation are unavailable in this experiment.
Use the preinstalled Python or R environment.
These limits replace only conflicting statements in the Environment section
above. All other task instructions remain in force."""

BIOMNIBENCH_DA_RECOVERY_PROMPT = (
    "The previous response was interrupted by a provider stream error. Continue "
    "the current task from where you left off. Finish the requested analysis and "
    "verify trace.md and answer.txt before stopping."
)

BIOMNIBENCH_DA_OUTPUT_RECOVERY_PROMPT = (
    "The previous response stopped before producing a valid submission. Continue "
    "the task autonomously without asking questions or waiting for confirmation. "
    "Complete the analysis, then verify that trace.md and answer.txt are regular, "
    "non-empty files before stopping."
)


class BiomniBenchDA(SubmissionBenchmark):
    benchmark = SubmissionBenchmarkId.BIOMNIBENCH_DA
    recovery_prompt = BIOMNIBENCH_DA_RECOVERY_PROMPT
    output_recovery_prompt = BIOMNIBENCH_DA_OUTPUT_RECOVERY_PROMPT
    required_outputs = ("trace.md", "answer.txt")
    retained_workspace_names = frozenset(required_outputs)
    answer_artifact = "answer.txt"

    def render_initial_solver_prompt(self, instruction: str) -> str:
        """Preserve the original Harbor instruction with factual path overrides."""

        if type(instruction) is not str or not instruction.strip():
            raise ValueError("BioMNIBench task instruction must be non-empty")
        return f"{instruction.rstrip()}\n\n{_EXPERIMENT_ENVIRONMENT}\n"

    def render_revision_solver_prompt(
        self,
        instruction: str,
        feedback_block: str,
        *,
        first_revision: bool,
    ) -> str:
        """Add revision state and feedback to the original task contract."""

        if type(feedback_block) is not str or not feedback_block.strip():
            raise ValueError("BioMNIBench revision feedback must be non-empty")
        if first_revision:
            context = self.render_initial_solver_prompt(instruction).rstrip()
        else:
            context = """Continue the current BioMNIBench-DA task.

The original task instruction and experiment environment remain in force."""
        return f"""{context}

## Revision round

The workspace contains the current `trace.md`, `answer.txt`, and supporting
files. Review the current work before editing it.

{feedback_block.strip()}

Use the feedback to revise the existing submission. Complete all outputs that
the task requires. If no file needs a change, leave the submission unchanged
and finish.
"""

    def output_errors(self, workspace: Path) -> list[str]:
        errors: list[str] = []
        for name in self.required_outputs:
            path = workspace / name
            try:
                value = os.lstat(path)
            except OSError:
                errors.append(f"missing_or_invalid: {name}")
                continue
            if not stat.S_ISREG(value.st_mode) or value.st_size == 0:
                errors.append(f"missing_or_invalid: {name}")
        return errors

    def render_submission(self, workspace: Path) -> str:
        return (workspace / "answer.txt").read_text(encoding="utf-8")

    def render_user_review(self, workspace: Path) -> str:
        return (
            "# trace.md\n\n"
            + (workspace / "trace.md").read_text(encoding="utf-8")
            + "\n\n# answer.txt\n\n"
            + (workspace / "answer.txt").read_text(encoding="utf-8")
        )

    def final_evidence(self, workspace: Path) -> tuple[FinalEvidence, ...]:
        evidence: list[FinalEvidence] = []
        for name in self.required_outputs:
            path = workspace / name
            if path.is_file():
                evidence.append(FinalEvidence(
                    name=f"final_{name}",
                    artifact=name,
                    content=path.read_text(encoding="utf-8", errors="replace"),
                ))
        return tuple(evidence)


BIOMNIBENCH_DA = BiomniBenchDA()
