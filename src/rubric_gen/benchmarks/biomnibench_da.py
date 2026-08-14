"""BioNMIbench-DA task and submission contract."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from rubric_gen.benchmarks import Benchmark
from rubric_gen.benchmarks.contracts import FinalEvidence, SubmissionBenchmark


BIOMNIBENCH_DA_PROMPT = """You are solving one BiomniBench-DA task in the current directory.

Read ./instruction.md and use only the files under ./data as task data.
Keep source inputs under ./data separate from generated work. Write derived
datasets, tables, plots, logs, and other supporting outputs under ./artifacts.
Do not read the source paper, source-paper figures, or source-paper supplements.
Do not inspect parent directories, Git metadata, other runs, evaluator files,
reference answers, environment variables, credentials, or absolute host paths.
Do not use web search, web fetch, browser tools, package installation, or network
commands. Use only the preinstalled analysis environment and local task data.

Work autonomously through the entire task. Do not enter an interactive planning
mode, ask the user to choose an approach, or pause for confirmation. Make
reasonable methodological choices yourself, document them in trace.md, and
finish the analysis in this invocation.

Required deliverables:
- ./trace.md: the full analysis trace requested by the instruction.
- ./answer.txt: the final plain-text answer requested by the instruction.
- ./artifacts/: supporting files that should persist across revision rounds.

Keep trace.md concise: summarize key commands, scripts, data shapes, metrics,
statistical choices, and limitations; do not paste long tables or full script
bodies when those scripts are saved in the workspace. Write a short provisional
answer.txt as soon as you have a viable result, then update it before stopping.

Use the preinstalled Python or R environment for analysis. If a desired package
is unavailable, use an installed alternative and record that limitation; do not
download code, create a package environment, or contact an external service.

You may write and run small Python or R scripts in this directory. Keep notes
of commands, intermediate counts, statistical choices, and limitations in
trace.md. Before stopping, verify that both trace.md and answer.txt exist and
are non-empty.
"""

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
    benchmark = Benchmark.BIOMNIBENCH_DA
    initial_prompt = BIOMNIBENCH_DA_PROMPT
    recovery_prompt = BIOMNIBENCH_DA_RECOVERY_PROMPT
    output_recovery_prompt = BIOMNIBENCH_DA_OUTPUT_RECOVERY_PROMPT
    revision_action = (
        "Re-run relevant checks and update trace.md and answer.txt. Store generated "
        "datasets, tables, plots, logs, and other supporting outputs under "
        "./artifacts, not ./data."
    )
    required_outputs = ("trace.md", "answer.txt")
    retained_workspace_names = frozenset(required_outputs)
    answer_artifact = "answer.txt"

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
