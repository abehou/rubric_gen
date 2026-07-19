"""Value types and durable state for submission-revision experiments."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.sessions import SolverSessionDriver
from rubric_gen.biomnibench.utils.paths import resolve_project_path
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy
from rubric_gen.biomnibench.revision.judge import (
    SubmissionJudge,
    SubmissionJudgeConfig,
)


_DIRECTORY_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _directory_component(value: object) -> str:
    text = str(value) if value is not None else "default"
    compact = _DIRECTORY_COMPONENT_RE.sub("-", text).strip(".-") or "default"
    if len(compact) <= 48:
        return compact
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:8]
    return f"{compact[:39]}-{digest}"


def revision_experiment_dir(
    args: argparse.Namespace,
    task_dir: Path,
    feedback_policy: FeedbackPolicy,
    rubric_set: Path | None,
    agent: AgentRunConfig,
) -> Path:
    """Derive an identity-bearing experiment directory for one configuration."""
    experiment_dir = resolve_project_path(args.experiment_dir)
    if (
        (args.resume or getattr(args, "restart", False))
        and not getattr(args, "all", False)
        and not getattr(args, "full_v_score", False)
        and os.path.lexists(experiment_dir)
    ):
        return experiment_dir
    policy_suffix = f"-{feedback_policy.value.replace('_', '-')}"
    for candidate in FeedbackPolicy:
        candidate_suffix = f"-{candidate.value.replace('_', '-')}"
        if experiment_dir.name.endswith(candidate_suffix):
            experiment_dir = experiment_dir.with_name(
                experiment_dir.name[: -len(candidate_suffix)] + policy_suffix
            )
            break
    rubric = (
        f"set-{_directory_component(rubric_set)}"
        if rubric_set is not None
        else _directory_component(args.rubric)
    )
    components = (
        f"t-{_directory_component(task_dir.name)}",
        f"fb-{_directory_component(feedback_policy.value.replace('_', '-'))}",
        f"n-{args.revision_rounds}",
        f"p-{_directory_component(agent.provider)}",
        f"m-{_directory_component(agent.model)}",
        f"j-{_directory_component(args.judge_model)}",
        f"rb-{rubric}",
        f"v-{_directory_component(args.review)}",
        f"sb-{int(agent.sandbox)}",
        f"st-{int(agent.skip_trust)}",
        f"web-{int(agent.allow_web)}",
        f"ap-{_directory_component(agent.approval_mode)}",
        f"mc-{args.max_review_chars if args.max_review_chars is not None else 'all'}",
        f"x-{_directory_component(agent.executable)}",
        f"raw-{int(agent.raw)}",
    )
    name = "--".join((experiment_dir.name, *components))
    if len(name) > 240:
        raise ValueError(
            "derived experiment directory name is too long; choose a shorter "
            "--experiment-dir base name"
        )
    return experiment_dir.with_name(name)


@dataclass(frozen=True)
class SubmissionRevisionConfig:
    """All inputs that define a linear submission-revision experiment."""

    task_dir: Path
    experiment_dir: Path
    revision_rounds: int
    agent: AgentRunConfig
    feedback_policy: FeedbackPolicy = FeedbackPolicy.FULL
    review: str = "trajectory"
    judge_model: str | None = None
    rubric_name: str | None = None
    rubric_set: Path | None = None
    max_review_chars: int | None = None
    resume: bool = False
    restart: bool = False
    show_progress: bool = True

    def __post_init__(self) -> None:
        if type(self.revision_rounds) is not int or self.revision_rounds < 0:
            raise ValueError("revision_rounds must be a non-negative integer")
        if self.review not in {"trace", "trajectory"}:
            raise ValueError("review must be trace or trajectory")
        if self.rubric_name is not None and self.rubric_set is not None:
            raise ValueError("rubric_name and rubric_set are mutually exclusive")
        if self.resume and self.restart:
            raise ValueError("resume and restart are mutually exclusive")
        if type(self.show_progress) is not bool:
            raise ValueError("show_progress must be a boolean")
        if type(self.agent.model) is not str or not self.agent.model.strip():
            raise ValueError("submission revision requires an explicit solver model")
        FeedbackPolicy(self.feedback_policy)

    def judge_config(self) -> SubmissionJudgeConfig:
        return SubmissionJudgeConfig(
            task_dir=self.task_dir,
            experiment_dir=self.experiment_dir,
            review=self.review,
            judge_model=self.judge_model,
            rubric_name=self.rubric_name,
            rubric_set=self.rubric_set,
            max_review_chars=self.max_review_chars,
            max_retries=self.agent.retries,
        )

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "SubmissionRevisionConfig":
        rubric_set = getattr(args, "rubric_set", None)
        resolved_rubric_set = resolve_project_path(rubric_set) if rubric_set else None
        feedback_policy = FeedbackPolicy(args.feedback_policy)
        task_dir = resolve_project_path(args.task)
        agent = AgentRunConfig.from_namespace(args)
        return cls(
            task_dir=task_dir,
            experiment_dir=revision_experiment_dir(
                args,
                task_dir,
                feedback_policy,
                resolved_rubric_set,
                agent,
            ),
            revision_rounds=args.revision_rounds,
            agent=agent,
            feedback_policy=feedback_policy,
            review=args.review,
            judge_model=args.judge_model,
            rubric_name=args.rubric,
            rubric_set=resolved_rubric_set,
            max_review_chars=args.max_review_chars,
            resume=args.resume,
            restart=getattr(args, "restart", False),
        )


@dataclass(frozen=True)
class RevisionDependencies:
    """Injectable session and judging collaborators for revision runs."""

    session: SolverSessionDriver
    judge: SubmissionJudge


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
