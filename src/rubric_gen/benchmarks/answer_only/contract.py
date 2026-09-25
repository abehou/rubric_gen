"""Answer-only deliverables; observable agent events remain the trajectory."""

from pathlib import Path
import json
import stat

from rubric_gen.benchmarks.base import FinalEvidence, SubmissionBenchmark, SubmissionBenchmarkId


class AnswerOnlyBenchmark(SubmissionBenchmark):
    required_outputs = ("answer.txt",)
    retained_workspace_names = frozenset(required_outputs)
    answer_artifact = "answer.txt"
    required_review = "workspace"
    recovery_prompt = "Continue the answer task and finish ./answer.txt. Do not retrieve external information."
    output_recovery_prompt = "Write your completed answer to a nonempty regular ./answer.txt file."

    def __init__(self, benchmark: SubmissionBenchmarkId):
        self.benchmark = benchmark

    def validate_task(self, task_dir: Path) -> None:
        super().validate_task(task_dir)
        metadata = json.loads((task_dir / "tests" / "source.json").read_text())
        if metadata["benchmark"] != self.benchmark.value:
            raise ValueError("answer-only task belongs to a different benchmark")
        if any((task_dir / "environment" / "data").iterdir()):
            raise ValueError("parametric tasks must not expose retrieval data")

    def required_task_paths(self, task_dir: Path) -> tuple[Path, ...]:
        return super().required_task_paths(task_dir) + (task_dir / "tests" / "source.json",)

    def render_initial_solver_prompt(self, instruction: str) -> str:
        if not instruction.strip():
            raise ValueError("task instruction must be nonempty")
        return instruction.rstrip() + """

## Experiment delivery
Answer from your existing knowledge and the supplied conversation/question only.
Write only the user-facing answer to ./answer.txt. Do not write a research trace
or reveal private reasoning. File reads/writes solely to deliver or revise this
answer are allowed. Do not search, browse, retrieve documents, run calculations,
install packages, inspect other directories, hidden tests, rubrics, credentials,
or environment variables. No research tools or external information are allowed.
Work autonomously and finish the answer without asking for experiment approval.
"""

    def render_revision_solver_prompt(self, instruction: str, feedback_block: str,
                                      *, first_revision: bool) -> str:
        if not feedback_block.strip():
            raise ValueError("revision feedback must be nonempty")
        return (self.render_initial_solver_prompt(instruction)
                + "\nRevise the existing ./answer.txt using the following feedback. "
                "Preserve correct content; do not invent facts or citations to satisfy feedback.\n\n"
                + feedback_block.strip() + "\n")

    def output_errors(self, workspace: Path) -> list[str]:
        try:
            info = (workspace / "answer.txt").lstat()
            if stat.S_ISREG(info.st_mode) and info.st_size and self.render_submission(workspace).strip():
                return []
        except (OSError, UnicodeError):
            pass
        return ["missing_or_invalid: answer.txt"]

    def render_submission(self, workspace: Path) -> str:
        return (workspace / "answer.txt").read_text(encoding="utf-8")

    def render_user_review(self, workspace: Path) -> str:
        return self.render_submission(workspace)

    def render_workspace_review(self, task_dir: Path, workspace: Path) -> str:
        return ("# Task context\n\n" + (task_dir / "instruction.md").read_text(encoding="utf-8")
                + "\n\n# Submitted answer\n\n" + self.render_submission(workspace))

    def final_evidence(self, workspace: Path) -> tuple[FinalEvidence, ...]:
        return (FinalEvidence("final_answer", "answer.txt", self.render_submission(workspace)),)


HEALTHBENCH_HARD = AnswerOnlyBenchmark(SubmissionBenchmarkId.HEALTHBENCH_HARD)
RESEARCHQA = AnswerOnlyBenchmark(SubmissionBenchmarkId.RESEARCHQA)
