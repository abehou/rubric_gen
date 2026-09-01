"""Value types and durable state for submission-revision experiments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.runtime.agents.sessions import SolverSessionDriver
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.judge import (
    SubmissionJudge,
    SubmissionJudgeConfig,
)
from rubric_gen.submission_revision.user_simulator import (
    SimulatedUserConfig,
    SimulatedUserFeedback,
)
from rubric_gen.benchmarks import SubmissionBenchmarkId


@dataclass(frozen=True)
class SubmissionRevisionConfig:
    """All inputs that define a linear submission-revision experiment."""

    task_dir: Path
    experiment_dir: Path
    max_revisions: int
    min_revisions: int
    seed_run_dir: Path
    pretreatment_rubric_dir: Path
    agent: AgentRunConfig
    seed_agent: AgentRunConfig
    solver_id: str
    experiment_id: str
    assignment_id: str
    condition_id: str
    replicate: int
    elicitation_seed_replicates: int
    execution_order: int
    optimizer_rubric_path: Path
    master_rubric_name: str
    benchmark: SubmissionBenchmarkId = SubmissionBenchmarkId.BIOMNIBENCH_DA
    rubric_proposer_max_retries: int = 1
    feedback_policy: FeedbackPolicy = FeedbackPolicy.FULL
    feedback_simulator: SimulatedUserConfig | None = None
    prompt_profile: PromptProfile = PromptProfile.BASE
    rubric_policy: RubricPolicy = RubricPolicy.FIXED
    rubric_proposer_model: str = "gpt-5.6-luna"
    review: str = "trace"
    judge_model: str | None = None
    max_review_chars: int | None = None
    resume: bool = False
    show_progress: bool = True
    progress_position: int | None = None

    def __post_init__(self) -> None:
        if type(self.max_revisions) is not int or self.max_revisions < 0:
            raise ValueError("max_revisions must be a non-negative integer")
        if (
            type(self.min_revisions) is not int
            or not 0 <= self.min_revisions <= self.max_revisions
        ):
            raise ValueError(
                "min_revisions must be between zero and max_revisions"
            )
        if not isinstance(self.pretreatment_rubric_dir, Path):
            raise ValueError("pretreatment_rubric_dir must be a path")
        if self.review not in {"trace", "trajectory", "workspace"}:
            raise ValueError("review must be trace, trajectory, or workspace")
        if (
            self.optimizer_rubric_path.is_symlink()
            or not self.optimizer_rubric_path.is_file()
        ):
            raise ValueError("optimizer_rubric_path must be a regular file")
        if (
            type(self.master_rubric_name) is not str
            or Path(self.master_rubric_name).name != self.master_rubric_name
            or not self.master_rubric_name
        ):
            raise ValueError("master_rubric_name must be a safe filename")
        if type(self.show_progress) is not bool:
            raise ValueError("show_progress must be a boolean")
        if self.progress_position is not None and (
            type(self.progress_position) is not int or self.progress_position < 0
        ):
            raise ValueError("progress_position must be a non-negative integer")
        if type(self.agent.model) is not str or not self.agent.model.strip():
            raise ValueError("submission revision requires an explicit solver model")
        if (
            type(self.seed_agent.model) is not str
            or not self.seed_agent.model.strip()
        ):
            raise ValueError("submission revision requires an explicit seed model")
        for name, value in (
            ("solver_id", self.solver_id),
            ("experiment_id", self.experiment_id),
            ("assignment_id", self.assignment_id),
            ("condition_id", self.condition_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if type(self.replicate) is not int or self.replicate < 1:
            raise ValueError("replicate must be a positive integer")
        if (
            type(self.elicitation_seed_replicates) is not int
            or self.elicitation_seed_replicates < 3
        ):
            raise ValueError("elicitation_seed_replicates must be at least three")
        if type(self.execution_order) is not int or self.execution_order < 1:
            raise ValueError("execution_order must be a positive integer")
        if (
            type(self.rubric_proposer_max_retries) is not int
            or self.rubric_proposer_max_retries < 0
        ):
            raise ValueError(
                "rubric_proposer_max_retries must be a non-negative integer"
            )
        feedback_policy = FeedbackPolicy(self.feedback_policy)
        if (
            feedback_policy is FeedbackPolicy.USER_SIMULATOR
        ) != (self.feedback_simulator is not None):
            raise ValueError(
                "feedback_simulator must be configured exactly when feedback_policy "
                "is user_simulator"
            )
        PromptProfile(self.prompt_profile)
        SubmissionBenchmarkId(self.benchmark)
        RubricPolicy(self.rubric_policy)
        if (
            type(self.rubric_proposer_model) is not str
            or not self.rubric_proposer_model.strip()
        ):
            raise ValueError("rubric_proposer_model must be nonempty")

    def judge_config(self) -> SubmissionJudgeConfig:
        return SubmissionJudgeConfig(
            task_dir=self.task_dir,
            experiment_dir=self.experiment_dir,
            benchmark=self.benchmark,
            review=self.review,
            judge_model=self.judge_model,
            rubric_name=None,
            rubric_set=None,
            rubric_path=self.optimizer_rubric_path,
            max_review_chars=self.max_review_chars,
        )

    def master_judge_config(self) -> SubmissionJudgeConfig:
        return SubmissionJudgeConfig(
            task_dir=self.task_dir,
            experiment_dir=self.experiment_dir,
            benchmark=self.benchmark,
            review=self.review,
            judge_model=self.judge_model,
            rubric_name=self.master_rubric_name,
            rubric_set=None,
            rubric_path=None,
            max_review_chars=self.max_review_chars,
        )

@dataclass(frozen=True)
class RevisionDependencies:
    """Injectable session and judging collaborators for revision runs."""

    session: SolverSessionDriver
    judge: SubmissionJudge
    master_judge: SubmissionJudge | None = None
    rubric_proposer: RubricProposer | None = None
    feedback_simulator: SimulatedUserFeedback | None = None


@dataclass(frozen=True)
class SubmissionRevisionResult:
    """Final persisted checkpoint of a completed revision run."""

    experiment_dir: Path
    session_id: str
    submission_ids: tuple[str, ...]
    scores: tuple[float, ...]
    fixed_original_scores: tuple[float, ...]
    stop_reason: str


class RevisionPhase(StrEnum):
    """Durable stages in the revision controller state machine."""

    READY_FOR_TURN = "ready_for_turn"
    TURN_IN_PROGRESS = "turn_in_progress"
    READY_FOR_JUDGE = "ready_for_judge"
    JUDGE_IN_PROGRESS = "judge_in_progress"
    FAILED_TURN = "failed_turn"
    COMPLETED = "completed"


@dataclass
class RevisionState:
    """Validated JSON-serializable controller state."""

    phase: RevisionPhase
    next_turn_index: int
    session_id: str | None
    effective_solver_model: str | None
    submission_ids: list[str]
    scores: list[float]
    fixed_original_scores: list[float]
    judge_attempts: dict[str, str]
    next_prompt: str
    stop_reason: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "next_turn_index": self.next_turn_index,
            "session_id": self.session_id,
            "effective_solver_model": self.effective_solver_model,
            "submission_ids": self.submission_ids,
            "scores": self.scores,
            "fixed_original_scores": self.fixed_original_scores,
            "judge_attempts": self.judge_attempts,
            "next_prompt": self.next_prompt,
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "RevisionState":
        phase = payload.get("phase")
        next_turn_index = payload.get("next_turn_index")
        session_id = payload.get("session_id")
        effective_model = payload.get("effective_solver_model")
        submission_ids = payload.get("submission_ids")
        scores = payload.get("scores")
        fixed_original_scores = payload.get("fixed_original_scores")
        judge_attempts = payload.get("judge_attempts")
        next_prompt = payload.get("next_prompt")
        stop_reason = payload.get("stop_reason")
        if (
            type(phase) is not str
            or type(next_turn_index) is not int
            or session_id is not None
            and type(session_id) is not str
            or effective_model is not None
            and type(effective_model) is not str
            or type(submission_ids) is not list
            or any(type(value) is not str for value in submission_ids)
            or type(scores) is not list
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 100
                for value in scores
            )
            or type(fixed_original_scores) is not list
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not 0 <= float(value) <= 100
                for value in fixed_original_scores
            )
            or len(fixed_original_scores) != len(scores)
            or type(judge_attempts) is not dict
            or any(
                type(key) is not str or type(value) is not str
                for key, value in judge_attempts.items()
            )
            or type(next_prompt) is not str
            or stop_reason not in {None, "no_change", "max_revisions"}
        ):
            raise RuntimeError("revision state has invalid fields")
        try:
            revision_phase = RevisionPhase(phase)
        except ValueError as exc:
            raise RuntimeError(f"revision state has an invalid phase: {phase}") from exc
        return cls(
            phase=revision_phase,
            next_turn_index=next_turn_index,
            session_id=session_id,
            effective_solver_model=effective_model,
            submission_ids=list(submission_ids),
            scores=[float(value) for value in scores],
            fixed_original_scores=[float(value) for value in fixed_original_scores],
            judge_attempts=dict(judge_attempts),
            next_prompt=next_prompt,
            stop_reason=stop_reason,
        )
