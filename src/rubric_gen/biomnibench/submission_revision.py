"""Linear, true-session self-revision of BiomniBench submissions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from tqdm.auto import trange

from rubric_gen.biomnibench.common import (
    PROGRESS_BAR_FORMAT,
    PROMPT,
    AgentRunConfig,
    TaskWorkspace,
    resolve_project_path,
)
from rubric_gen.biomnibench.session_drivers import (
    CliSolverSessionDriver,
    SolverSessionDriver,
)
from rubric_gen.biomnibench.submission_feedback import (
    FeedbackPolicy,
    project_feedback,
)
from rubric_gen.biomnibench.submission_revision_artifacts import (
    LIVE_ROOT_PREFIX as _LIVE_ROOT_PREFIX,
    REVISION_EXPERIMENT_KIND as _REVISION_EXPERIMENT_KIND,
    copy_solution_workspace as _copy_solution_workspace,
    make_read_only as _make_read_only,
    make_tree_read_only as _make_tree_read_only,
    read_json_object as _read_json_object,
    remove_created_live_tree as _remove_created_live_tree,
    remove_revision_experiment as _remove_revision_experiment,
    remove_live_tree as _remove_tree,
    sha256_file as _sha256_file,
    solution_tree_sha256 as _solution_tree_sha256,
    tree_sha256 as _tree_sha256,
    validate_live_root as _validate_live_root,
    verify_submission_snapshot as _verify_submission_snapshot,
    write_json as _write_json,
    write_json_atomic as _write_json_atomic,
    write_live_root_sentinel as _write_live_root_sentinel,
)
from rubric_gen.biomnibench.submission_revision_judge import (
    SCORING_IDENTITY_KEYS as _SCORING_IDENTITY_KEYS,
    BiomniSubmissionJudge,
    JudgeArtifacts as JudgeArtifacts,
    SubmissionJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric as _resolve_optimizer_rubric,
)


_DIRECTORY_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _directory_component(value: object) -> str:
    text = str(value) if value is not None else "default"
    compact = _DIRECTORY_COMPONENT_RE.sub("-", text).strip(".-") or "default"
    if len(compact) <= 48:
        return compact
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:8]
    return f"{compact[:39]}-{digest}"


def _revision_experiment_dir(
    args: argparse.Namespace,
    task_dir: Path,
    feedback_policy: FeedbackPolicy,
    rubric_set: Path | None,
    agent: AgentRunConfig,
) -> Path:
    experiment_dir = resolve_project_path(args.experiment_dir)
    if (
        args.resume
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
            experiment_dir=_revision_experiment_dir(
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
    session: SolverSessionDriver
    judge: SubmissionJudge


@dataclass(frozen=True)
class SubmissionRevisionResult:
    experiment_dir: Path
    session_id: str
    submission_ids: tuple[str, ...]
    scores: tuple[int, ...]


class _RevisionPhase(StrEnum):
    READY_FOR_TURN = "ready_for_turn"
    TURN_IN_PROGRESS = "turn_in_progress"
    READY_FOR_JUDGE = "ready_for_judge"
    JUDGE_IN_PROGRESS = "judge_in_progress"
    FAILED_TURN = "failed_turn"
    COMPLETED = "completed"


@dataclass
class _RevisionState:
    phase: _RevisionPhase
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
    def from_json(cls, payload: dict[str, object]) -> "_RevisionState":
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
            revision_phase = _RevisionPhase(phase)
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


class _SolverTurnFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _extract_scoring_identity(
    payload: dict[str, object],
    *,
    context: str,
) -> dict[str, object]:
    missing = [key for key in _SCORING_IDENTITY_KEYS if key not in payload]
    if missing:
        raise RuntimeError(f"{context} lacks scoring identity: {', '.join(missing)}")
    return {key: payload[key] for key in _SCORING_IDENTITY_KEYS}


class SubmissionRevisionController:
    """Run a fixed-length linear revision conversation for one task."""

    def __init__(
        self,
        config: SubmissionRevisionConfig,
        dependencies: RevisionDependencies | None = None,
    ) -> None:
        self.config = config
        self.experiment_dir = Path(config.experiment_dir).resolve()
        self.task_dir = Path(config.task_dir).resolve()
        judge_config = config.judge_config()
        self.rubric = _resolve_optimizer_rubric(judge_config)
        self.instruction_sha256 = _sha256_file(self.task_dir / "instruction.md")
        self.data_sha256 = _tree_sha256(self.task_dir / "environment" / "data")
        self.dependencies = dependencies or RevisionDependencies(
            session=CliSolverSessionDriver(config.agent),
            judge=BiomniSubmissionJudge(judge_config, self.rubric),
        )
        reported_scoring_identity = self.dependencies.judge.scoring_identity()
        if set(reported_scoring_identity) != set(_SCORING_IDENTITY_KEYS):
            raise RuntimeError(
                "submission judge returned an incomplete scoring identity"
            )
        self.scoring_identity = _extract_scoring_identity(
            reported_scoring_identity,
            context="submission judge",
        )
        if self.scoring_identity["rendered_rubric_sha256"] != self.rubric.sha256:
            raise RuntimeError("submission judge resolved a different optimizer rubric")

    def _experiment_identity(self) -> dict[str, object]:
        return {
            "task_id": self.task_dir.name,
            "task_dir": str(self.task_dir),
            "revision_rounds": self.config.revision_rounds,
            "provider": self.config.agent.provider,
            "model": self.config.agent.model,
            "executable": self.config.agent.executable,
            "sandbox_requested": self.config.agent.sandbox,
            "allow_web": self.config.agent.allow_web,
            "approval_mode": self.config.agent.approval_mode,
            "skip_trust": self.config.agent.skip_trust,
            "feedback_policy": FeedbackPolicy(self.config.feedback_policy).value,
            "review": self.config.review,
            "judge_model": self.config.judge_model,
            "max_review_chars": self.config.max_review_chars,
            "rubric_name": self.config.rubric_name,
            "rubric_set": (
                str(Path(self.config.rubric_set).resolve())
                if self.config.rubric_set is not None
                else None
            ),
            "rubric_sha256": self.rubric.sha256,
            "instruction_sha256": self.instruction_sha256,
            "data_sha256": self.data_sha256,
        }

    def run(self) -> SubmissionRevisionResult:
        initialized = False
        completed = False
        if self.config.restart and os.path.lexists(self.experiment_dir):
            _remove_revision_experiment(self.experiment_dir, self.task_dir)
        if self.config.resume:
            state, live_root, workspace = self._load_resume()
            initialized = True
        else:
            if os.path.lexists(self.experiment_dir):
                raise FileExistsError(
                    f"experiment directory already exists: {self.experiment_dir}"
                )
            live_root = Path(tempfile.mkdtemp(prefix=_LIVE_ROOT_PREFIX))
            try:
                _write_live_root_sentinel(live_root, self.experiment_dir)
            except BaseException:
                _remove_created_live_tree(live_root)
                raise
            workspace = live_root / "workspace"
            state = _RevisionState(
                phase=_RevisionPhase.READY_FOR_TURN,
                next_turn_index=0,
                session_id=None,
                effective_solver_model=None,
                submission_ids=[],
                scores=[],
                judge_attempts={},
                next_prompt=PROMPT,
            )
        try:
            if not initialized:
                TaskWorkspace(self.task_dir, workspace).validate()
                self._initialize(workspace, live_root, state)
                initialized = True
            total = self.config.revision_rounds + 1
            if state.phase in {
                _RevisionPhase.TURN_IN_PROGRESS,
                _RevisionPhase.FAILED_TURN,
            }:
                raise RuntimeError(
                    "experiment cannot resume an uncertain or failed solver turn"
                )
            progress_initial = len(state.scores)
            turns = (
                trange(
                    progress_initial,
                    total,
                    initial=progress_initial,
                    total=total,
                    desc=f"revise {self.task_dir.name}",
                    unit="submission",
                    dynamic_ncols=True,
                    bar_format=PROGRESS_BAR_FORMAT,
                )
                if self.config.show_progress
                else range(progress_initial, total)
            )
            for _ in turns:
                if state.phase is _RevisionPhase.READY_FOR_TURN:
                    self._run_solver_turn(state, workspace)
                if state.phase in {
                    _RevisionPhase.READY_FOR_JUDGE,
                    _RevisionPhase.JUDGE_IN_PROGRESS,
                }:
                    self._run_judge_boundary(state)
                if state.phase not in {
                    _RevisionPhase.READY_FOR_TURN,
                    _RevisionPhase.COMPLETED,
                }:
                    raise RuntimeError(f"invalid revision state: {state.phase}")
            self._validate_scored_boundaries(state)
            state.phase = _RevisionPhase.COMPLETED
            self._write_state(state)
            self._append_event(
                {
                    "event": "experiment_completed",
                    "session_id": state.session_id,
                    "submission_count": len(state.submission_ids),
                    "scores": state.scores,
                }
            )
            completed = True
            return SubmissionRevisionResult(
                experiment_dir=self.experiment_dir,
                session_id=state.session_id or "",
                submission_ids=tuple(state.submission_ids),
                scores=tuple(state.scores),
            )
        finally:
            if completed or not initialized:
                _remove_tree(live_root, self.experiment_dir)
            if completed:
                self._update_manifest({"live_workspace_removed": True})

    def _initialize(
        self,
        workspace: Path,
        live_root: Path,
        state: _RevisionState,
    ) -> None:
        self.experiment_dir.mkdir(parents=True)
        TaskWorkspace(self.task_dir, workspace).prepare()
        _make_read_only(workspace / "instruction.md")
        _make_tree_read_only(workspace / "data")
        _write_json(
            self.experiment_dir / "manifest.json",
            {
                "schema_version": 1,
                "kind": _REVISION_EXPERIMENT_KIND,
                **self._experiment_identity(),
                "submission_count": self.config.revision_rounds + 1,
                "live_workspace_dir": str(workspace),
                "live_workspace_removed": False,
                "session_id": None,
                "effective_solver_model": None,
                "scoring_identity": self.scoring_identity,
            },
        )
        self._persist_rubric()
        self._write_state(state)

    def _load_resume(self) -> tuple[_RevisionState, Path, Path]:
        if not self.experiment_dir.is_dir():
            raise FileNotFoundError(
                f"experiment directory does not exist: {self.experiment_dir}"
            )
        manifest = _read_json_object(
            self.experiment_dir / "manifest.json",
            "revision manifest",
        )
        if manifest.get("schema_version") != 1:
            raise RuntimeError("revision manifest has an unsupported schema")
        for key, value in self._experiment_identity().items():
            if manifest.get(key) != value:
                raise RuntimeError(f"resume configuration changed: {key}")
        if manifest.get("scoring_identity") != self.scoring_identity:
            raise RuntimeError("resume scoring identity changed")
        workspace_value = manifest.get("live_workspace_dir")
        if type(workspace_value) is not str or not workspace_value:
            raise RuntimeError("revision manifest has no live workspace")
        workspace = Path(workspace_value)
        live_root = workspace.parent
        self._verify_frozen_rubric()
        self._verify_canonical_task_inputs()
        state = self._read_state()
        if workspace.name != "workspace" or not workspace.is_absolute():
            raise RuntimeError("revision manifest has an invalid live workspace path")
        if os.path.lexists(live_root):
            _validate_live_root(live_root, self.experiment_dir)
        if workspace.is_symlink() or not workspace.is_dir():
            total = self.config.revision_rounds + 1
            if (
                not os.path.lexists(live_root)
                and state.phase is _RevisionPhase.COMPLETED
                and state.next_turn_index == total
                and len(state.submission_ids) == len(state.scores) == total
            ):
                self._validate_resume_state(state, None, manifest)
                return state, live_root, workspace
            raise RuntimeError(f"live revision workspace is unavailable: {workspace}")
        self._verify_live_task_inputs(workspace)
        self._validate_resume_state(state, workspace, manifest)
        return state, live_root, workspace

    def _validate_resume_state(
        self,
        state: _RevisionState,
        workspace: Path | None,
        manifest: dict[str, object],
    ) -> None:
        if state.phase in {
            _RevisionPhase.TURN_IN_PROGRESS,
            _RevisionPhase.FAILED_TURN,
        }:
            raise RuntimeError(
                "experiment stopped during an uncertain or failed solver turn"
            )
        total = self.config.revision_rounds + 1
        if not 0 <= state.next_turn_index <= total:
            raise RuntimeError("revision state has an invalid turn index")
        if state.phase in {
            _RevisionPhase.READY_FOR_JUDGE,
            _RevisionPhase.JUDGE_IN_PROGRESS,
        }:
            valid_counts = (
                len(state.submission_ids) == state.next_turn_index
                and len(state.scores) == state.next_turn_index - 1
            )
        else:
            valid_counts = (
                len(state.submission_ids) == len(state.scores) == state.next_turn_index
            )
        if not valid_counts:
            raise RuntimeError("revision state boundary counts are inconsistent")
        expected_submission_ids = [
            f"s{index:03d}" for index in range(state.next_turn_index)
        ]
        if state.submission_ids != expected_submission_ids:
            raise RuntimeError("revision state has invalid submission identities")
        if state.phase is _RevisionPhase.COMPLETED and state.next_turn_index != total:
            raise RuntimeError("completed revision state has missing submissions")
        if workspace is None and state.phase is not _RevisionPhase.COMPLETED:
            raise RuntimeError(
                "live workspace is required for an incomplete experiment"
            )
        if state.phase is _RevisionPhase.READY_FOR_JUDGE:
            expected_judge_attempts = set(state.submission_ids[: len(state.scores)])
        else:
            expected_judge_attempts = set(state.submission_ids)
        if set(state.judge_attempts) != expected_judge_attempts or any(
            len(attempt_id) != 32
            or any(character not in "0123456789abcdef" for character in attempt_id)
            for attempt_id in state.judge_attempts.values()
        ):
            raise RuntimeError("revision state has invalid judge attempt identities")
        if state.next_turn_index and (
            not state.session_id or not state.effective_solver_model
        ):
            raise RuntimeError("revision state is missing solver identity")
        if manifest.get("session_id") != state.session_id:
            raise RuntimeError("manifest and revision state disagree on session ID")
        if manifest.get("effective_solver_model") != state.effective_solver_model:
            raise RuntimeError("manifest and revision state disagree on solver model")
        turn_dirs = sorted((self.experiment_dir / "turns").glob("turn-*"))
        expected_turns = [
            self.experiment_dir / "turns" / f"turn-{index:03d}"
            for index in range(state.next_turn_index)
        ]
        if turn_dirs != expected_turns:
            raise RuntimeError("experiment contains an uncertain solver turn")
        for submission_id in state.submission_ids:
            _verify_submission_snapshot(
                self.experiment_dir / "submissions" / submission_id
            )
        if state.submission_ids and workspace is not None:
            snapshot = _read_json_object(
                self.experiment_dir
                / "submissions"
                / state.submission_ids[-1]
                / "snapshot.json",
                "submission snapshot",
            )
            if snapshot.get("workspace_sha256") != _solution_tree_sha256(workspace):
                raise RuntimeError("live workspace changed after the last boundary")
        expected_prompt = self._validate_scored_boundaries(state)
        if state.next_prompt != expected_prompt:
            raise RuntimeError("revision state next prompt disagrees with feedback")
        if manifest.get("scoring_identity") != self.scoring_identity:
            raise RuntimeError("revision manifest has the wrong scoring identity")

    def _run_solver_turn(self, state: _RevisionState, workspace: Path) -> None:
        turn_index = state.next_turn_index
        state.phase = _RevisionPhase.TURN_IN_PROGRESS
        self._write_state(state)
        turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
        turn_dir.mkdir(parents=True)
        (turn_dir / "prompt.txt").write_text(state.next_prompt)
        try:
            self._execute_solver_turn(state, workspace, turn_dir, turn_index)
        except BaseException as exc:
            if state.phase is not _RevisionPhase.FAILED_TURN:
                exit_code = exc.exit_code if isinstance(exc, _SolverTurnFailure) else 1
                reason = str(exc) or type(exc).__name__
                try:
                    self._mark_turn_failed(
                        state,
                        turn_dir,
                        turn_index,
                        reason,
                        exit_code,
                    )
                except Exception as record_error:
                    raise RuntimeError(
                        f"solver turn {turn_index} failed and could not be sealed"
                    ) from record_error
            raise

    def _execute_solver_turn(
        self,
        state: _RevisionState,
        workspace: Path,
        turn_dir: Path,
        turn_index: int,
    ) -> None:

        def record_early_session_id(session_id: str) -> None:
            if state.session_id not in {None, session_id}:
                raise RuntimeError("solver reported a different provider session")
            state.session_id = session_id
            self._record_session_id(session_id)
            self._write_state(state)

        if turn_index == 0:
            turn = self.dependencies.session.start(
                workspace,
                state.next_prompt,
                turn_dir,
                on_session_id=record_early_session_id,
            )
            record_early_session_id(turn.session_id)
        else:
            if state.session_id is None:
                raise RuntimeError("revision state is missing the provider session")
            turn = self.dependencies.session.resume(
                workspace,
                state.next_prompt,
                turn_dir,
                state.session_id,
            )
            if turn.session_id != state.session_id:
                raise RuntimeError("solver resumed a different provider session")
        self._record_effective_solver_model(state, turn.model)
        if turn.exit_code != 0:
            raise _SolverTurnFailure(
                f"provider exited with code {turn.exit_code}", turn.exit_code
            )
        try:
            self._verify_live_task_inputs(workspace)
            self._validate_submission_outputs(workspace)
            _solution_tree_sha256(workspace)
        except (OSError, RuntimeError) as exc:
            raise _SolverTurnFailure(str(exc), 2) from exc
        _make_tree_read_only(turn_dir)
        submission_id = f"s{turn_index:03d}"
        trajectories = [
            self.experiment_dir
            / "turns"
            / f"turn-{index:03d}"
            / "trajectory.stream.jsonl"
            for index in range(turn_index + 1)
        ]
        self._snapshot_submission(
            submission_id,
            workspace,
            trajectories,
            state.session_id or "",
        )
        self._append_event(
            {
                "event": "turn_completed",
                "turn": turn_index,
                "session_id": state.session_id,
                "trajectory_sha256": _sha256_file(turn.trajectory_path),
            }
        )
        state.submission_ids.append(submission_id)
        state.next_turn_index += 1
        state.phase = _RevisionPhase.READY_FOR_JUDGE
        self._write_state(state)

    def _run_judge_boundary(self, state: _RevisionState) -> None:
        self._validate_scored_boundaries(state)
        submission_id = state.submission_ids[-1]
        turn_index = state.next_turn_index - 1
        attempt_id = state.judge_attempts.get(submission_id)
        if attempt_id is None:
            attempt_id = secrets.token_hex(16)
            state.judge_attempts[submission_id] = attempt_id
        state.phase = _RevisionPhase.JUDGE_IN_PROGRESS
        self._write_state(state)
        submission_dir = self.experiment_dir / "submissions" / submission_id
        _verify_submission_snapshot(submission_dir)
        self._verify_canonical_task_inputs()
        artifacts = self.dependencies.judge.evaluate(submission_dir, attempt_id)
        self._verify_canonical_task_inputs()
        _verify_submission_snapshot(submission_dir)
        self._pin_or_verify_scoring_identity(artifacts.score_validation_path)
        feedback = project_feedback(
            artifacts.score_validation_path,
            artifacts.evaluation_path,
            self.rubric.text,
            self.rubric.sha256,
            self.config.feedback_policy,
        )
        feedback_path = self.experiment_dir / "feedback" / f"{submission_id}.json"
        if feedback_path.exists():
            if (
                _read_json_object(feedback_path, "revision feedback")
                != feedback.payload
            ):
                raise RuntimeError("existing feedback disagrees with judge artifacts")
        else:
            _write_json_atomic(feedback_path, feedback.payload)
            _make_read_only(feedback_path)
        state.scores.append(feedback.score)
        state.next_prompt = feedback.prompt
        state.phase = _RevisionPhase.READY_FOR_TURN
        self._write_state(state)
        self._append_event(
            {
                "event": "submission_judged",
                "submission_id": submission_id,
                "turn": turn_index,
                "judge_attempt_id": attempt_id,
                "score": feedback.score,
                "feedback_policy": FeedbackPolicy(self.config.feedback_policy).value,
                "feedback_sha256": _sha256_file(feedback_path),
            }
        )

    def _validate_scored_boundaries(self, state: _RevisionState) -> str:
        expected_prompt = PROMPT
        for index, score in enumerate(state.scores):
            submission_id = f"s{index:03d}"
            submission_dir = self.experiment_dir / "submissions" / submission_id
            _verify_submission_snapshot(submission_dir)
            attempt_id = state.judge_attempts.get(submission_id)
            if attempt_id is None:
                raise RuntimeError("scored submission has no judge attempt identity")
            artifacts = self.dependencies.judge.validate(submission_dir, attempt_id)
            self._pin_or_verify_scoring_identity(artifacts.score_validation_path)
            projected = project_feedback(
                artifacts.score_validation_path,
                artifacts.evaluation_path,
                self.rubric.text,
                self.rubric.sha256,
                self.config.feedback_policy,
            )
            feedback = _read_json_object(
                self.experiment_dir / "feedback" / f"{submission_id}.json",
                "revision feedback",
            )
            if projected.score != score or feedback != projected.payload:
                raise RuntimeError(
                    "stored feedback disagrees with validated judge artifacts"
                )
            expected_prompt = projected.prompt
        return expected_prompt

    def _persist_rubric(self) -> None:
        rubric_path = self.experiment_dir / "rubric" / "r0000.txt"
        if rubric_path.is_file():
            if _sha256_file(rubric_path) != self.rubric.sha256:
                raise RuntimeError("persisted optimizer rubric changed")
            return
        if os.path.lexists(rubric_path):
            raise RuntimeError("optimizer rubric path is not a regular file")
        rubric_path.parent.mkdir()
        rubric_path.write_text(self.rubric.text)
        _make_read_only(rubric_path)

    def _verify_frozen_rubric(self) -> None:
        rubric_path = self.experiment_dir / "rubric" / "r0000.txt"
        if rubric_path.is_symlink() or not rubric_path.is_file():
            raise RuntimeError("persisted optimizer rubric is missing")
        if rubric_path.read_text(encoding="utf-8") != self.rubric.text:
            raise RuntimeError("persisted optimizer rubric changed")

    def _write_state(self, state: _RevisionState) -> None:
        _write_json_atomic(self.experiment_dir / "state.json", state.as_json())

    def _read_state(self) -> _RevisionState:
        payload = _read_json_object(
            self.experiment_dir / "state.json", "revision state"
        )
        return _RevisionState.from_json(payload)

    def _update_manifest(self, updates: dict[str, object]) -> None:
        manifest_path = self.experiment_dir / "manifest.json"
        manifest = _read_json_object(manifest_path, "revision manifest")
        manifest.update(updates)
        _write_json_atomic(manifest_path, manifest)

    def _record_session_id(self, session_id: str) -> None:
        if type(session_id) is not str or not session_id.strip():
            raise RuntimeError("solver did not return a persistent session ID")
        manifest = _read_json_object(
            self.experiment_dir / "manifest.json",
            "revision manifest",
        )
        previous = manifest.get("session_id")
        if previous not in {None, session_id}:
            raise RuntimeError("solver changed provider session ID")
        self._update_manifest({"session_id": session_id})

    def _record_effective_solver_model(
        self,
        state: _RevisionState,
        model: str,
    ) -> None:
        if type(model) is not str or not model.strip():
            raise RuntimeError("solver did not report an effective model")
        if state.effective_solver_model not in {None, model}:
            raise RuntimeError("solver changed model during the revision loop")
        state.effective_solver_model = model
        self._update_manifest({"effective_solver_model": model})
        self._write_state(state)

    def _pin_or_verify_scoring_identity(self, validation_path: Path) -> None:
        validation = _read_json_object(validation_path, "optimizer score validation")
        identity = _extract_scoring_identity(
            validation,
            context="optimizer score validation",
        )
        manifest = _read_json_object(
            self.experiment_dir / "manifest.json",
            "revision manifest",
        )
        if manifest.get("scoring_identity") != self.scoring_identity:
            raise RuntimeError("optimizer scoring identity changed in the manifest")
        if identity != self.scoring_identity:
            raise RuntimeError("optimizer scoring identity changed during revision")

    def _mark_turn_failed(
        self,
        state: _RevisionState,
        turn_dir: Path,
        turn_index: int,
        reason: str,
        exit_code: int,
    ) -> None:
        status_path = turn_dir / "status.json"
        if turn_dir.is_symlink() or not turn_dir.is_dir():
            raise RuntimeError("solver turn directory is invalid")
        turn_dir.chmod(stat.S_IMODE(os.lstat(turn_dir).st_mode) | stat.S_IRWXU)
        if status_path.is_symlink():
            raise RuntimeError("solver turn status is a symbolic link")
        if status_path.is_file():
            status_path.chmod(
                stat.S_IMODE(os.lstat(status_path).st_mode)
                | stat.S_IRUSR
                | stat.S_IWUSR
            )
        status = (
            _read_json_object(status_path, "solver turn status")
            if status_path.is_file()
            else {}
        )
        provider_exit_code = status.get("exit_code")
        status.update(
            {
                "status": "failed",
                "provider_exit_code": provider_exit_code,
                "exit_code": exit_code,
                "validation_errors": [reason],
            }
        )
        _write_json(status_path, status)
        state.phase = _RevisionPhase.FAILED_TURN
        self._write_state(state)
        self._append_event(
            {
                "event": "turn_failed",
                "turn": turn_index,
                "exit_code": exit_code,
                "session_id": state.session_id,
                "reason": reason,
            }
        )
        _make_tree_read_only(turn_dir)

    def _validate_submission_outputs(self, workspace: Path) -> None:
        invalid: list[str] = []
        for name in ("trace.md", "answer.txt"):
            path = workspace / name
            try:
                path_stat = os.lstat(path)
            except OSError:
                invalid.append(name)
                continue
            if not stat.S_ISREG(path_stat.st_mode) or path_stat.st_size == 0:
                invalid.append(name)
        if invalid:
            raise RuntimeError(
                "solver submission is missing or has invalid required outputs: "
                + ", ".join(invalid)
            )

    def _verify_live_task_inputs(self, workspace: Path) -> None:
        if _sha256_file(workspace / "instruction.md") != self.instruction_sha256:
            raise RuntimeError("solver modified the task instruction")
        if _tree_sha256(workspace / "data") != self.data_sha256:
            raise RuntimeError("solver modified the canonical task data")

    def _verify_canonical_task_inputs(self) -> None:
        if _sha256_file(self.task_dir / "instruction.md") != self.instruction_sha256:
            raise RuntimeError(
                "canonical task instruction changed during the experiment"
            )
        if _tree_sha256(self.task_dir / "environment" / "data") != self.data_sha256:
            raise RuntimeError("canonical task data changed during the experiment")

    def _snapshot_submission(
        self,
        submission_id: str,
        workspace: Path,
        trajectories: list[Path],
        session_id: str,
    ) -> Path:
        submission_dir = self.experiment_dir / "submissions" / submission_id
        snapshot_workspace = submission_dir / "workspace"
        submission_dir.mkdir(parents=True)
        _copy_solution_workspace(workspace, snapshot_workspace)
        _make_tree_read_only(snapshot_workspace)

        cumulative = submission_dir / "trajectory.stream.jsonl"
        with cumulative.open("wb") as output:
            for trajectory in trajectories:
                raw = trajectory.read_bytes()
                output.write(raw)
                if raw and not raw.endswith(b"\n"):
                    output.write(b"\n")
        status_path = submission_dir / "status.json"
        _write_json(
            status_path,
            {
                "schema_version": 1,
                "task": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "workspace_dir": str(snapshot_workspace),
                "provider": self.config.agent.provider,
                "session_id": session_id,
                "submission_id": submission_id,
                "exit_code": 0,
            },
        )
        workspace_sha256 = _tree_sha256(snapshot_workspace)
        trajectory_sha256 = _sha256_file(cumulative)
        snapshot_path = submission_dir / "snapshot.json"
        _write_json(
            snapshot_path,
            {
                "schema_version": 1,
                "submission_id": submission_id,
                "session_id": session_id,
                "workspace_sha256": workspace_sha256,
                "trajectory_sha256": trajectory_sha256,
            },
        )
        for path in (cumulative, status_path, snapshot_path):
            _make_read_only(path)
        _make_read_only(submission_dir)
        self._append_event(
            {
                "event": "submission_snapshotted",
                "submission_id": submission_id,
                "workspace_sha256": workspace_sha256,
                "trajectory_sha256": trajectory_sha256,
            }
        )
        return submission_dir

    def _append_event(self, payload: dict[str, object]) -> None:
        events = self.experiment_dir / "events.jsonl"
        with events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())


def run_submission_revision(
    config: SubmissionRevisionConfig,
) -> SubmissionRevisionResult:
    return SubmissionRevisionController(config).run()
