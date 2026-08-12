"""Value types and durable state for submission-revision experiments."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.agent.sessions import SolverSessionDriver
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy
from rubric_gen.biomnibench.revision.evolution import RubricEvolution, RubricEvolver
from rubric_gen.biomnibench.revision.judge import (
    SubmissionJudge,
    SubmissionJudgeConfig,
)
from rubric_gen.biomnibench.revision.user_simulator import (
    SimulatedUserConfig,
    SimulatedUserFeedback,
)


@dataclass(frozen=True)
class SubmissionRevisionConfig:
    """All inputs that define a linear submission-revision experiment."""

    task_dir: Path
    experiment_dir: Path
    revision_rounds: int
    seed_run_dir: Path
    agent: AgentRunConfig
    experiment_id: str
    assignment_id: str
    condition_id: str
    replicate: int
    execution_order: int
    seed_experiment_id: str | None = None
    judge_max_retries: int = 1
    rubric_proposer_max_retries: int = 1
    feedback_policy: FeedbackPolicy = FeedbackPolicy.FULL
    feedback_simulator: SimulatedUserConfig | None = None
    prompt_profile: PromptProfile = PromptProfile.BASE
    rubric_evolution: RubricEvolution = RubricEvolution.STATIC
    rubric_auditor_model: str = "gpt-5.6-luna"
    rubric_auditor_base_url: str | None = None
    rubric_auditor_query_limit: int = 12
    rubric_proposer_model: str = "gpt-5.6-luna"
    rubric_proposer_base_url: str | None = None
    review: str = "trace"
    judge_model: str | None = None
    judge_base_url: str | None = None
    rubric_name: str | None = None
    rubric_set: Path | None = None
    max_review_chars: int | None = None
    resume: bool = False
    show_progress: bool = True
    progress_position: int | None = None
    publish_report: bool = False

    def __post_init__(self) -> None:
        if type(self.revision_rounds) is not int or self.revision_rounds < 0:
            raise ValueError("revision_rounds must be a non-negative integer")
        if self.review not in {"trace", "trajectory"}:
            raise ValueError("review must be trace or trajectory")
        if self.rubric_name is not None and self.rubric_set is not None:
            raise ValueError("rubric_name and rubric_set are mutually exclusive")
        if type(self.show_progress) is not bool:
            raise ValueError("show_progress must be a boolean")
        if self.progress_position is not None and (
            type(self.progress_position) is not int or self.progress_position < 0
        ):
            raise ValueError("progress_position must be a non-negative integer")
        if type(self.publish_report) is not bool:
            raise ValueError("publish_report must be a boolean")
        if type(self.agent.model) is not str or not self.agent.model.strip():
            raise ValueError("submission revision requires an explicit solver model")
        for name, value in (
            ("experiment_id", self.experiment_id),
            ("seed_experiment_id", self.seed_experiment_id or self.experiment_id),
            ("assignment_id", self.assignment_id),
            ("condition_id", self.condition_id),
        ):
            if type(value) is not str or not value.strip():
                raise ValueError(f"{name} must be nonempty")
        if type(self.replicate) is not int or self.replicate < 1:
            raise ValueError("replicate must be a positive integer")
        if type(self.execution_order) is not int or self.execution_order < 1:
            raise ValueError("execution_order must be a positive integer")
        for name, retries in (
            ("judge_max_retries", self.judge_max_retries),
            ("rubric_proposer_max_retries", self.rubric_proposer_max_retries),
        ):
            if type(retries) is not int or retries < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        feedback_policy = FeedbackPolicy(self.feedback_policy)
        if (
            feedback_policy is FeedbackPolicy.SIMULATED_USER
        ) != (self.feedback_simulator is not None):
            raise ValueError(
                "feedback_simulator must be configured exactly when feedback_policy "
                "is simulated_user"
            )
        PromptProfile(self.prompt_profile)
        RubricEvolution(self.rubric_evolution)
        for name, model in (
            ("rubric_auditor_model", self.rubric_auditor_model),
            ("rubric_proposer_model", self.rubric_proposer_model),
        ):
            if type(model) is not str or not model.strip():
                raise ValueError(f"{name} must be nonempty")
        if (
            type(self.rubric_auditor_query_limit) is not int
            or self.rubric_auditor_query_limit < 1
        ):
            raise ValueError("rubric_auditor_query_limit must be positive")

    def judge_config(self) -> SubmissionJudgeConfig:
        return SubmissionJudgeConfig(
            task_dir=self.task_dir,
            experiment_dir=self.experiment_dir,
            review=self.review,
            judge_model=self.judge_model,
            base_url=self.judge_base_url,
            rubric_name=self.rubric_name,
            rubric_set=self.rubric_set,
            max_review_chars=self.max_review_chars,
            max_retries=self.judge_max_retries,
        )

@dataclass(frozen=True)
class RevisionDependencies:
    """Injectable session and judging collaborators for revision runs."""

    session: SolverSessionDriver
    judge: SubmissionJudge
    evolver: RubricEvolver | None = None
    feedback_simulator: SimulatedUserFeedback | None = None


@dataclass(frozen=True)
class SubmissionRevisionResult:
    """Final persisted boundary of a completed revision run."""

    experiment_dir: Path
    session_id: str
    submission_ids: tuple[str, ...]
    scores: tuple[int, ...]


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
    scores: list[int]
    judge_attempts: dict[str, str]
    next_prompt: str

    def as_json(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "phase": self.phase,
            "next_turn_index": self.next_turn_index,
            "session_id": self.session_id,
            "effective_solver_model": self.effective_solver_model,
            "submission_ids": self.submission_ids,
            "scores": self.scores,
            "judge_attempts": self.judge_attempts,
            "next_prompt": self.next_prompt,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "RevisionState":
        phase = payload.get("phase")
        next_turn_index = payload.get("next_turn_index")
        session_id = payload.get("session_id")
        effective_model = payload.get("effective_solver_model")
        submission_ids = payload.get("submission_ids")
        scores = payload.get("scores")
        judge_attempts = payload.get("judge_attempts")
        next_prompt = payload.get("next_prompt")
        if (
            payload.get("schema_version") != 1
            or type(phase) is not str
            or type(next_turn_index) is not int
            or session_id is not None
            and type(session_id) is not str
            or effective_model is not None
            and type(effective_model) is not str
            or type(submission_ids) is not list
            or any(type(value) is not str for value in submission_ids)
            or type(scores) is not list
            or any(type(value) is not int for value in scores)
            or any(not 0 <= value <= 100 for value in scores)
            or type(judge_attempts) is not dict
            or any(
                type(key) is not str or type(value) is not str
                for key, value in judge_attempts.items()
            )
            or type(next_prompt) is not str
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
            scores=list(scores),
            judge_attempts=dict(judge_attempts),
            next_prompt=next_prompt,
        )
