"""Linear, true-session self-revision of BiomniBench submissions."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rubric_gen.biomnibench.common import AgentRunConfig, PROMPT, TaskWorkspace
from rubric_gen.biomnibench.judges import (
    BiomniBenchJudgeRunner,
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
)
from rubric_gen.biomnibench.rubric_scoring import RUBRIC_SCORER_VERSION
from rubric_gen.biomnibench.session_drivers import (
    CliSolverSessionDriver,
    SolverSessionDriver,
)
from rubric_gen.biomnibench.submission_feedback import (
    FeedbackPolicy,
    project_feedback,
)
from rubric_gen.biomnibench.task_rubric_compiler import resolve_rubric_bundle


_EXCLUDED_SOLUTION_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "data",
        "instruction.md",
    }
)

_LIVE_ROOT_PREFIX = "biomnibench-revision-live-"
_LIVE_ROOT_SENTINEL = ".rubric-gen-live-root.json"

_SCORING_IDENTITY_KEYS = (
    "scorer_version",
    "judge_source_sha256",
    "judge_runner_sha256",
    "scorer_module_sha256",
    "effective_judge_model",
    "review_mode",
    "max_review_chars",
    "rubric_source",
    "rubric_set_id",
    "rubric_id",
    "structured_rubric_sha256",
    "rendered_rubric_sha256",
    "manifest_sha256",
)


@dataclass(frozen=True)
class JudgeArtifacts:
    score_validation_path: Path
    evaluation_path: Path


class SubmissionJudge(Protocol):
    def scoring_identity(self) -> dict[str, object]: ...

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts: ...

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts: ...


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

    def __post_init__(self) -> None:
        if type(self.revision_rounds) is not int or self.revision_rounds < 0:
            raise ValueError("revision_rounds must be a non-negative integer")
        if self.review not in {"trace", "trajectory"}:
            raise ValueError("review must be trace or trajectory")
        if self.rubric_name is not None and self.rubric_set is not None:
            raise ValueError("rubric_name and rubric_set are mutually exclusive")
        if type(self.agent.model) is not str or not self.agent.model.strip():
            raise ValueError("submission revision requires an explicit solver model")
        FeedbackPolicy(self.feedback_policy)


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


@dataclass(frozen=True)
class _FrozenRubric:
    text: str
    sha256: str
    source: str
    rubric_set_id: str | None
    rubric_id: str | None
    structured_rubric_sha256: str | None
    manifest_sha256: str | None


@dataclass
class _RevisionState:
    phase: str
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


class _SolverTurnFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class BiomniSubmissionJudge:
    """Run the existing task judge against one immutable submission snapshot."""

    def __init__(self, config: SubmissionRevisionConfig, rubric: _FrozenRubric) -> None:
        self.config = config
        self.rubric = rubric
        self.experiment_dir = Path(config.experiment_dir).resolve()
        self.task_dir = Path(config.task_dir).resolve()
        self.rubric_set = (
            Path(config.rubric_set).resolve() if config.rubric_set is not None else None
        )

    def scoring_identity(self) -> dict[str, object]:
        runner = BiomniBenchJudgeRunner(
            JudgeRunConfig(
                run_dir=self.experiment_dir,
                tasks_dir=self.task_dir.parent,
                review=self.config.review,
                model=self.config.judge_model,
                rubric_name=self.config.rubric_name,
                rubric_set=self.rubric_set,
                max_review_chars=self.config.max_review_chars,
            )
        )
        judge_path = runner.find_judge(self.task_dir)
        return {
            "scorer_version": RUBRIC_SCORER_VERSION,
            "judge_source_sha256": _sha256_file(judge_path),
            "judge_runner_sha256": runner.judge_runner_sha256(),
            "scorer_module_sha256": runner.scorer_module_sha256(),
            "effective_judge_model": runner.judge_model(os.environ.copy()),
            "review_mode": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "rubric_source": self.rubric.source,
            "rubric_set_id": self.rubric.rubric_set_id,
            "rubric_id": self.rubric.rubric_id,
            "structured_rubric_sha256": self.rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": self.rubric.sha256,
            "manifest_sha256": self.rubric.manifest_sha256,
        }

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        evaluation_root = self._evaluation_root(submission_dir, attempt_id)
        if os.path.lexists(evaluation_root):
            try:
                artifacts = self.validate(submission_dir, attempt_id)
                _make_tree_read_only(evaluation_root)
                return artifacts
            except (OSError, RuntimeError, SystemExit, ValueError):
                _remove_owned_evaluation_tree(
                    evaluation_root,
                    self.experiment_dir / "evaluations",
                )
        run_dir = _prepare_evaluation_run(submission_dir, evaluation_root)
        runner, target = self._runner_and_target(run_dir)
        record = runner.review_target(target)
        if record.get("status") != "completed" or type(record.get("score")) is not int:
            raise RuntimeError("optimizer judge did not produce a validated score")
        artifacts = self._validated_cached_artifacts(
            runner,
            target,
            evaluation_root,
            submission_dir,
        )
        _make_tree_read_only(evaluation_root)
        return artifacts

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        evaluation_root = self._evaluation_root(submission_dir, attempt_id)
        run_dir = evaluation_root / "run"
        if (
            evaluation_root.is_symlink()
            or run_dir.is_symlink()
            or not evaluation_root.is_dir()
            or not run_dir.is_dir()
        ):
            raise RuntimeError(f"invalid optimizer evaluation: {evaluation_root}")
        runner, target = self._runner_and_target(run_dir)
        return self._validated_cached_artifacts(
            runner,
            target,
            evaluation_root,
            submission_dir,
        )

    def _evaluation_root(self, submission_dir: Path, attempt_id: str) -> Path:
        if (
            type(attempt_id) is not str
            or len(attempt_id) != 32
            or any(character not in "0123456789abcdef" for character in attempt_id)
        ):
            raise ValueError("judge attempt ID must be 128-bit lowercase hex")
        return (
            self.experiment_dir
            / "evaluations"
            / submission_dir.name
            / self.rubric.sha256
            / attempt_id
        )

    def _runner_and_target(
        self,
        run_dir: Path,
    ) -> tuple[BiomniBenchJudgeRunner, JudgeTarget]:
        runner = BiomniBenchJudgeRunner(
            JudgeRunConfig(
                run_dir=run_dir,
                tasks_dir=self.task_dir.parent,
                review=self.config.review,
                model=self.config.judge_model,
                rubric_name=self.config.rubric_name,
                rubric_set=self.rubric_set,
                max_review_chars=self.config.max_review_chars,
                resume=True,
            )
        )
        targets = runner.discover_targets()
        if len(targets) != 1:
            raise RuntimeError("submission judge did not resolve exactly one task")
        target = targets[0]
        resolved = runner.resolve_rubric(target)
        if _sha256_text(resolved.text) != self.rubric.sha256:
            raise RuntimeError("optimizer rubric changed during the revision loop")
        return runner, target

    def _validated_cached_artifacts(
        self,
        runner: BiomniBenchJudgeRunner,
        target: JudgeTarget,
        evaluation_root: Path,
        submission_dir: Path,
    ) -> JudgeArtifacts:
        run_dir = evaluation_root / "run"
        if _tree_sha256(run_dir / "workspace") != _tree_sha256(
            submission_dir / "workspace"
        ):
            raise RuntimeError("optimizer evaluation workspace changed")
        if _sha256_file(run_dir / "trajectory.stream.jsonl") != _sha256_file(
            submission_dir / "trajectory.stream.jsonl"
        ):
            raise RuntimeError("optimizer evaluation trajectory changed")
        output_dir = runner.output_dir(target)
        completed = runner.completed_record(JudgeAttempt(target, 1))
        if completed is None:
            raise RuntimeError(
                f"invalid cached optimizer evaluation: {evaluation_root}"
            )
        validation = _read_json_object(
            output_dir / "score_validation.json",
            "optimizer score validation",
        )
        if validation.get("rendered_rubric_sha256") != self.rubric.sha256:
            raise RuntimeError("optimizer score does not attest the frozen rubric")
        if validation.get("task") != self.task_dir.name:
            raise RuntimeError("optimizer score attests a different task")
        if validation.get("review_mode") != self.config.review:
            raise RuntimeError("optimizer score attests a different review mode")
        if validation.get("review_input_sha256") != _sha256_file(
            output_dir / "judge_input_trace.md"
        ):
            raise RuntimeError("optimizer score does not attest the reviewed trace")
        if validation.get("answer_input_sha256") != _sha256_file(
            output_dir / "judge_input_answer.txt"
        ):
            raise RuntimeError("optimizer score does not attest the reviewed answer")
        return JudgeArtifacts(
            score_validation_path=output_dir / "score_validation.json",
            evaluation_path=output_dir / "evaluation.json",
        )


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
        self.rubric = _resolve_optimizer_rubric(config, self.task_dir)
        self.instruction_sha256 = _sha256_file(self.task_dir / "instruction.md")
        self.data_sha256 = _tree_sha256(self.task_dir / "environment" / "data")
        self.dependencies = dependencies or RevisionDependencies(
            session=CliSolverSessionDriver(config.agent),
            judge=BiomniSubmissionJudge(config, self.rubric),
        )
        self.scoring_identity = self.dependencies.judge.scoring_identity()
        if set(self.scoring_identity) != set(_SCORING_IDENTITY_KEYS):
            raise RuntimeError(
                "submission judge returned an incomplete scoring identity"
            )
        if self.scoring_identity["rendered_rubric_sha256"] != self.rubric.sha256:
            raise RuntimeError("submission judge resolved a different optimizer rubric")

    def run(self) -> SubmissionRevisionResult:
        initialized = False
        completed = False
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
                _force_remove_directory(live_root)
                raise
            workspace = live_root / "workspace"
            state = _RevisionState(
                phase="ready_for_turn",
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
            if state.phase in {"turn_in_progress", "failed_turn"}:
                raise RuntimeError(
                    "experiment cannot resume an uncertain or failed solver turn"
                )
            while len(state.scores) < total:
                if state.phase == "ready_for_turn":
                    self._run_solver_turn(state, workspace)
                if state.phase in {"ready_for_judge", "judge_in_progress"}:
                    self._run_judge_boundary(state)
                if state.phase not in {"ready_for_turn", "completed"}:
                    raise RuntimeError(f"invalid revision state: {state.phase}")
            self._validate_scored_boundaries(state)
            state.phase = "completed"
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
                "task_id": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "revision_rounds": self.config.revision_rounds,
                "submission_count": self.config.revision_rounds + 1,
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
        expected = {
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
        for key, value in expected.items():
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
                and state.phase == "completed"
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
        if state.phase in {"turn_in_progress", "failed_turn"}:
            raise RuntimeError(
                "experiment stopped during an uncertain or failed solver turn"
            )
        allowed_phases = {
            "ready_for_turn",
            "ready_for_judge",
            "judge_in_progress",
            "completed",
        }
        if state.phase not in allowed_phases:
            raise RuntimeError(f"revision state has an invalid phase: {state.phase}")
        total = self.config.revision_rounds + 1
        if not 0 <= state.next_turn_index <= total:
            raise RuntimeError("revision state has an invalid turn index")
        if state.phase in {"ready_for_judge", "judge_in_progress"}:
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
        if state.phase == "completed" and state.next_turn_index != total:
            raise RuntimeError("completed revision state has missing submissions")
        if workspace is None and state.phase != "completed":
            raise RuntimeError(
                "live workspace is required for an incomplete experiment"
            )
        if state.phase == "ready_for_judge":
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
        state.phase = "turn_in_progress"
        self._write_state(state)
        turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
        turn_dir.mkdir(parents=True)
        (turn_dir / "prompt.txt").write_text(state.next_prompt)
        try:
            self._execute_solver_turn(state, workspace, turn_dir, turn_index)
        except BaseException as exc:
            if state.phase != "failed_turn":
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
        state.phase = "ready_for_judge"
        self._write_state(state)

    def _run_judge_boundary(self, state: _RevisionState) -> None:
        self._validate_scored_boundaries(state)
        submission_id = state.submission_ids[-1]
        turn_index = state.next_turn_index - 1
        attempt_id = state.judge_attempts.get(submission_id)
        if attempt_id is None:
            attempt_id = secrets.token_hex(16)
            state.judge_attempts[submission_id] = attempt_id
        state.phase = "judge_in_progress"
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
        state.phase = "ready_for_turn"
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
        return _RevisionState(
            phase=phase,
            next_turn_index=next_turn_index,
            session_id=session_id,
            effective_solver_model=effective_model,
            submission_ids=list(submission_ids),
            scores=list(scores),
            judge_attempts=dict(judge_attempts),
            next_prompt=next_prompt,
        )

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
        missing = [key for key in _SCORING_IDENTITY_KEYS if key not in validation]
        if missing:
            raise RuntimeError(
                "optimizer score validation lacks scoring identity: "
                + ", ".join(missing)
            )
        identity = {key: validation[key] for key in _SCORING_IDENTITY_KEYS}
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
        state.phase = "failed_turn"
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


def _resolve_optimizer_rubric(
    config: SubmissionRevisionConfig,
    task_dir: Path,
) -> _FrozenRubric:
    if config.rubric_set is not None:
        bundle = resolve_rubric_bundle(
            Path(config.rubric_set),
            task_dir.name,
        )
        text = bundle.rendered_text
        source = "rubric-set"
        rubric_set_id = bundle.rubric_set_id
        rubric_id = bundle.rubric_id
        structured_rubric_sha256 = bundle.rubric_sha256
        manifest_sha256 = bundle.task_manifest_sha256
    else:
        name = config.rubric_name or "rubric.txt"
        if Path(name).name != name:
            raise ValueError("rubric_name must be a filename under task tests")
        path = task_dir / "tests" / name
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"optimizer rubric does not exist: {path}")
        text = path.read_text(encoding="utf-8")
        source = "task-local"
        rubric_set_id = None
        rubric_id = None
        structured_rubric_sha256 = None
        manifest_sha256 = None
    if not text.strip():
        raise ValueError("optimizer rubric is empty")
    return _FrozenRubric(
        text=text,
        sha256=_sha256_text(text),
        source=source,
        rubric_set_id=rubric_set_id,
        rubric_id=rubric_id,
        structured_rubric_sha256=structured_rubric_sha256,
        manifest_sha256=manifest_sha256,
    )


def _copy_solution_workspace(source: Path, destination: Path) -> None:
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        if child.name in _EXCLUDED_SOLUTION_NAMES:
            continue
        _copy_solution_entry(child, destination / child.name)


def _prepare_evaluation_run(submission_dir: Path, evaluation_root: Path) -> Path:
    if os.path.lexists(evaluation_root):
        raise FileExistsError(f"evaluation already exists: {evaluation_root}")
    run_dir = evaluation_root / "run"
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True)
    _copy_solution_workspace(submission_dir / "workspace", workspace)
    _make_tree_read_only(workspace)
    shutil.copyfile(
        submission_dir / "trajectory.stream.jsonl",
        run_dir / "trajectory.stream.jsonl",
        follow_symlinks=False,
    )
    source_status = _read_json_object(
        submission_dir / "status.json",
        "submission status",
    )
    source_status["workspace_dir"] = str(workspace)
    evaluation_trajectory = run_dir / "trajectory.stream.jsonl"
    evaluation_status = run_dir / "status.json"
    _write_json(evaluation_status, source_status)
    _make_read_only(evaluation_trajectory)
    _make_read_only(evaluation_status)
    return run_dir


def _verify_submission_snapshot(submission_dir: Path) -> None:
    snapshot = _read_json_object(
        submission_dir / "snapshot.json", "submission snapshot"
    )
    if snapshot.get("submission_id") != submission_dir.name:
        raise RuntimeError("submission snapshot has a mismatched identity")
    if snapshot.get("workspace_sha256") != _tree_sha256(submission_dir / "workspace"):
        raise RuntimeError("submission workspace changed after snapshotting")
    if snapshot.get("trajectory_sha256") != _sha256_file(
        submission_dir / "trajectory.stream.jsonl"
    ):
        raise RuntimeError("submission trajectory changed after snapshotting")


def _copy_solution_entry(source: Path, destination: Path) -> None:
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        destination.mkdir()
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            _copy_solution_entry(child, destination / child.name)
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a special file: {source}")
    shutil.copyfile(source, destination, follow_symlinks=False)


def _tree_sha256(root: Path) -> str:
    return _hash_tree(root, excluded_names=frozenset())


def _solution_tree_sha256(root: Path) -> str:
    return _hash_tree(root, excluded_names=_EXCLUDED_SOLUTION_NAMES)


def _hash_tree(root: Path, *, excluded_names: frozenset[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if Path(relative).parts[0] in excluded_names:
            continue
        path_stat = os.lstat(path)
        if stat.S_ISDIR(path_stat.st_mode):
            digest.update(b"D\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise RuntimeError(f"snapshot contains a non-regular file: {relative}")
        raw = path.read_bytes()
        digest.update(b"F\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _make_tree_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        _make_read_only(path)


def _make_read_only(path: Path) -> None:
    path.chmod(stat.S_IMODE(os.lstat(path).st_mode) & ~0o222)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def _write_live_root_sentinel(root: Path, experiment_dir: Path) -> None:
    _write_json(
        root / _LIVE_ROOT_SENTINEL,
        {
            "schema_version": 1,
            "kind": "rubric-gen-submission-revision-live-root",
            "experiment_dir": str(experiment_dir.resolve()),
        },
    )
    _make_read_only(root / _LIVE_ROOT_SENTINEL)


def _validate_live_root(root: Path, experiment_dir: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        root.is_symlink()
        or not root.is_dir()
        or not root.name.startswith(_LIVE_ROOT_PREFIX)
        or root.parent.resolve() != temp_root
    ):
        raise RuntimeError(f"invalid live revision root: {root}")
    sentinel = root / _LIVE_ROOT_SENTINEL
    if sentinel.is_symlink() or not sentinel.is_file():
        raise RuntimeError(f"live revision root sentinel is missing: {root}")
    payload = _read_json_object(sentinel, "live revision root sentinel")
    if payload != {
        "schema_version": 1,
        "kind": "rubric-gen-submission-revision-live-root",
        "experiment_dir": str(experiment_dir.resolve()),
    }:
        raise RuntimeError(f"live revision root sentinel does not match: {root}")


def _remove_tree(root: Path, experiment_dir: Path) -> None:
    if not os.path.lexists(root):
        return
    _validate_live_root(root, experiment_dir)
    _force_remove_directory(root)


def _remove_owned_evaluation_tree(root: Path, evaluations_dir: Path) -> None:
    if not os.path.lexists(root):
        return
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"invalid optimizer evaluation root: {root}")
    base = evaluations_dir.absolute()
    candidate = root.absolute()
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise RuntimeError(
            f"optimizer evaluation escaped its artifact root: {root}"
        ) from exc
    if len(relative.parts) != 3 or any(
        path.is_symlink()
        for path in (
            base,
            base / relative.parts[0],
            base / relative.parts[0] / relative.parts[1],
        )
    ):
        raise RuntimeError(f"optimizer evaluation escaped its artifact root: {root}")
    _force_remove_directory(root)


def _force_remove_directory(root: Path) -> None:
    directories = [
        path for path in root.rglob("*") if not path.is_symlink() and path.is_dir()
    ]
    for path in [
        *sorted(directories, key=lambda item: len(item.parts), reverse=True),
        root,
    ]:
        path.chmod(stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRWXU)
    shutil.rmtree(root)
    if os.path.lexists(root):
        raise RuntimeError(f"failed to remove owned directory tree: {root}")


def _read_json_object(path: Path, context: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{context} is not valid JSON: {path}") from exc
    if type(value) is not dict:
        raise RuntimeError(f"{context} must be a JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
