"""PaperBench Code-Dev task and submission contract."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from rubric_gen.benchmarks.base import (
    FinalEvidence,
    SubmissionBenchmark,
    SubmissionBenchmarkId,
)
from rubric_gen.benchmarks.paperbench_code_dev.submission import render_submission_tree
from rubric_gen.benchmarks.paperbench_code_dev.dataset import (
    PAPERBENCH_DEV_PAPERS,
    PAPERBENCH_RESULTS_PAPERS,
    validate_paperbench_code_dataset,
)


PAPERBENCH_CODE_DEV_PROMPT = """You are solving one PaperBench Code-Dev task in the current directory.

Read ./instruction.md first. The source paper, author addendum, allowed assets,
and blacklist are under ./data. Do not inspect parent directories, Git metadata,
other runs, evaluator files, hidden rubrics, environment variables, credentials,
or absolute host paths. Do not use web search, web fetch, browser tools, package
installation, or network commands. Do not use any resource named in
./data/blacklist.txt.

This live directory is not a Git checkout. Do not run Git commands. Inspect
files directly. The sandbox does not provide literal /tmp. Use $TMPDIR for
temporary files.

Work autonomously through the entire task. Implement as many core contributions
from the paper as possible in ./submission. The graded deliverable is the code,
not a description of code. Prefer a coherent, runnable implementation with
tests, configuration, and a useful README. Make reasonable choices yourself.
Do not enter an interactive planning mode, ask the user to choose an approach,
or pause for confirmation.

Required deliverables:
- ./submission/: the paper-replication source tree, including README.md.

Keep all implementation files inside ./submission. Keep source inputs under
./data unchanged. You can run local checks with the preinstalled environment.
If a dependency or dataset is unavailable, implement the integration interface,
use a small local test where useful, and state the limitation. Do not claim that
an experiment or check ran unless it did. Before stopping, verify that the
submission contains real source code and a non-empty README.md.
"""

PAPERBENCH_CODE_DEV_RECOVERY_PROMPT = (
    "The previous response was interrupted by a provider stream error. Continue "
    "the current task from where you left off. Finish the requested source tree "
    "and verify submission/README.md before stopping. This workspace has no Git "
    "metadata or literal /tmp. Do not run Git commands. Use $TMPDIR for temporary "
    "files."
)

PAPERBENCH_CODE_DEV_OUTPUT_RECOVERY_PROMPT = (
    "The previous response stopped before producing a valid PaperBench "
    "submission. Continue autonomously. Complete the source tree under submission, "
    "then verify that submission/README.md is regular and non-empty. Do not run "
    "Git commands. Use $TMPDIR instead of literal /tmp."
)


class PaperBenchCodeDev(SubmissionBenchmark):
    benchmark = SubmissionBenchmarkId.PAPERBENCH_CODE_DEV
    initial_prompt = PAPERBENCH_CODE_DEV_PROMPT
    recovery_prompt = PAPERBENCH_CODE_DEV_RECOVERY_PROMPT
    output_recovery_prompt = PAPERBENCH_CODE_DEV_OUTPUT_RECOVERY_PROMPT
    revision_instructions = """Read ./instruction.md and the allowed files under ./data again.
Obey ./data/blacklist.txt. Keep ./data unchanged. Do not inspect parent
directories, evaluator files, environment variables, credentials, or absolute
host paths. Do not use the network or install packages. Do not run Git commands.
Use $TMPDIR for temporary files. Inspect the implementation under ./submission.
Run relevant local checks. Update the source and README.md when evidence supports
a change. Keep all implementation files under ./submission. Work autonomously."""
    required_outputs = ("submission",)
    retained_workspace_names = frozenset(required_outputs)
    required_review = "workspace"

    def validate_dataset(self, tasks_dir: Path, task_ids: tuple[str, ...]) -> None:
        if task_ids == PAPERBENCH_DEV_PAPERS:
            source_split = "dev"
        elif task_ids == PAPERBENCH_RESULTS_PAPERS:
            source_split = "all"
        else:
            raise ValueError(
                "PaperBench Code-Dev tasks must equal the official 3-paper dev "
                "split or the official 20-paper all split"
            )
        validate_paperbench_code_dataset(
            tasks_dir,
            source_split=source_split,
        )

    def required_task_paths(self, task_dir: Path) -> tuple[Path, ...]:
        return super().required_task_paths(task_dir) + (
            task_dir / "environment" / "data" / "paper.md",
            task_dir / "tests" / "paperbench.json",
        )

    def output_errors(self, workspace: Path) -> list[str]:
        submission = workspace / "submission"
        try:
            submission_value = os.lstat(submission)
        except OSError:
            return ["missing_or_invalid: submission"]
        if not stat.S_ISDIR(submission_value.st_mode):
            return ["missing_or_invalid: submission"]
        readme = submission / "README.md"
        try:
            readme_value = os.lstat(readme)
        except OSError:
            return ["missing_or_invalid: submission/README.md"]
        if not stat.S_ISREG(readme_value.st_mode) or readme_value.st_size == 0:
            return ["missing_or_invalid: submission/README.md"]
        return []

    def render_submission(self, workspace: Path) -> str:
        return render_submission_tree(workspace)

    def render_user_review(self, workspace: Path) -> str:
        return render_submission_tree(workspace)

    def render_workspace_review(self, task_dir: Path, workspace: Path) -> str:
        paper_path = task_dir / "environment" / "data" / "paper.md"
        if paper_path.is_symlink() or not paper_path.is_file():
            raise ValueError(f"PaperBench paper is missing: {paper_path}")
        parts = ["# Source paper\n\n" + paper_path.read_text(encoding="utf-8")]
        for heading, path in (
            ("Author addendum", task_dir / "environment" / "data" / "addendum.md"),
            ("Judge addendum", task_dir / "tests" / "judge.addendum.md"),
        ):
            if path.is_symlink():
                raise ValueError(f"PaperBench input must not be a symlink: {path}")
            if path.is_file():
                parts.append(f"# {heading}\n\n" + path.read_text(encoding="utf-8"))
        parts.append("# Submitted code\n\n" + self.render_submission(workspace))
        return "\n\n".join(parts)

    def final_evidence(self, workspace: Path) -> tuple[FinalEvidence, ...]:
        return (FinalEvidence(
            name="final_submission",
            artifact="submission source tree",
            content=self.render_submission(workspace),
        ),)


PAPERBENCH_CODE_DEV = PaperBenchCodeDev()
