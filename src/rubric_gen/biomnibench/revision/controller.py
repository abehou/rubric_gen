"""Stateful controller for linear BiomniBench submission revision."""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import tempfile
from pathlib import Path

from tqdm.auto import trange

from rubric_gen.biomnibench.agent.prompts import PromptMitigation, solver_prompt
from rubric_gen.biomnibench.agent.sessions import CliSolverSessionDriver
from rubric_gen.biomnibench.agent.workspaces import TaskWorkspace
from rubric_gen.biomnibench.utils.progress import PROGRESS_BAR_FORMAT
from rubric_gen.biomnibench.revision.feedback import (
    FeedbackPolicy,
    project_feedback,
)
from rubric_gen.biomnibench.revision.models import (
    RevisionDependencies,
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
    SubmissionRevisionResult,
)
from rubric_gen.biomnibench.revision.artifacts import (
    LIVE_ROOT_PREFIX as _LIVE_ROOT_PREFIX,
    live_root_parent as _live_root_parent,
    REVISION_EXPERIMENT_KIND as _REVISION_EXPERIMENT_KIND,
    compact_historical_workspace as _compact_historical_workspace,
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
from rubric_gen.biomnibench.revision.judge import (
    SCORING_IDENTITY_KEYS as _SCORING_IDENTITY_KEYS,
    BiomniSubmissionJudge,
    JudgeArtifacts as JudgeArtifacts,
    resolve_optimizer_rubric as _resolve_optimizer_rubric,
)
from rubric_gen.biomnibench.revision.store import (
    RevisionStore,
    extract_scoring_identity as _extract_scoring_identity,
)
from rubric_gen.biomnibench.revision.reports import publish_revision_report
from rubric_gen.biomnibench.visualization.revisions import write_revision_score_plot


class _SolverTurnFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


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
        self.store = RevisionStore(
            self.experiment_dir,
            rubric_text=self.rubric.text,
            rubric_sha256=self.rubric.sha256,
            scoring_identity=self.scoring_identity,
        )

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
            "mitigation": PromptMitigation(self.config.mitigation).value,
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
            live_root = Path(
                tempfile.mkdtemp(
                    prefix=_LIVE_ROOT_PREFIX,
                    dir=_live_root_parent(),
                )
            )
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
                next_prompt=solver_prompt(self.config.mitigation),
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
                    desc=(
                        f"revise {self.task_dir.name} "
                        f"[{FeedbackPolicy(self.config.feedback_policy).value}]"
                    ),
                    unit="round",
                    dynamic_ncols=True,
                    bar_format=PROGRESS_BAR_FORMAT,
                    position=self.config.progress_position,
                    leave=self.config.progress_position is None,
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
            compaction = self._compact_historical_submissions(state)
            if self.config.publish_report:
                publish_revision_report(self.experiment_dir)
            self._append_event(
                {
                    "event": "experiment_completed",
                    "session_id": state.session_id,
                    "submission_count": len(state.submission_ids),
                    "scores": state.scores,
                    "historical_workspace_files_removed": compaction[0],
                    "historical_workspace_logical_bytes_removed": compaction[1],
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
        desired_live_parent = _live_root_parent()
        if (
            os.path.lexists(live_root)
            and live_root.parent.resolve() != desired_live_parent
        ):
            _validate_live_root(live_root, self.experiment_dir)
            relocated_root = desired_live_parent / live_root.name
            if os.path.lexists(relocated_root):
                _validate_live_root(relocated_root, self.experiment_dir)
                _remove_tree(relocated_root, self.experiment_dir)
            shutil.copytree(
                live_root,
                relocated_root,
                symlinks=True,
                copy_function=shutil.copyfile,
            )
            _validate_live_root(relocated_root, self.experiment_dir)
            workspace = relocated_root / "workspace"
            manifest["live_workspace_dir"] = str(workspace)
            try:
                _write_json_atomic(self.experiment_dir / "manifest.json", manifest)
            except BaseException:
                _remove_tree(relocated_root, self.experiment_dir)
                raise
            _remove_tree(live_root, self.experiment_dir)
            live_root = relocated_root
        self._verify_frozen_rubric()
        self._verify_canonical_task_inputs()
        state = self._read_state()
        if state.phase is _RevisionPhase.COMPLETED:
            self._compact_historical_submissions(state)
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
        if state.phase in {
            _RevisionPhase.FAILED_TURN,
            _RevisionPhase.TURN_IN_PROGRESS,
        }:
            self._recover_failed_solver_boundary(state, workspace, manifest)
        self._validate_resume_state(state, workspace, manifest)
        return state, live_root, workspace

    def _recover_failed_solver_boundary(
        self,
        state: _RevisionState,
        workspace: Path,
        manifest: dict[str, object],
    ) -> None:
        """Promote a safely completed legacy solver failure to judging."""
        turn_index = state.next_turn_index
        if not 0 <= turn_index < self.config.revision_rounds + 1:
            raise RuntimeError("failed revision state has an invalid turn index")
        expected_submission_ids = [f"s{index:03d}" for index in range(turn_index)]
        if (
            state.submission_ids != expected_submission_ids
            or len(state.scores) != turn_index
            or set(state.judge_attempts) != set(state.submission_ids)
        ):
            raise RuntimeError("failed revision state boundary counts are inconsistent")
        if (
            not state.session_id
            or not state.effective_solver_model
            or manifest.get("session_id") != state.session_id
            or manifest.get("effective_solver_model") != state.effective_solver_model
        ):
            raise RuntimeError("failed revision state has inconsistent solver identity")
        if state.next_prompt != self._validate_scored_boundaries(state):
            raise RuntimeError(
                "failed revision state next prompt disagrees with feedback"
            )

        turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
        expected_turns = [
            self.experiment_dir / "turns" / f"turn-{index:03d}"
            for index in range(turn_index + 1)
        ]
        if sorted((self.experiment_dir / "turns").glob("turn-*")) != expected_turns:
            raise RuntimeError("experiment contains an uncertain failed solver turn")
        status_path = turn_dir / "status.json"
        trajectory_path = turn_dir / "trajectory.stream.jsonl"
        if (
            turn_dir.is_symlink()
            or not turn_dir.is_dir()
            or status_path.is_symlink()
            or not status_path.is_file()
            or trajectory_path.is_symlink()
            or not trajectory_path.is_file()
            or trajectory_path.stat().st_size == 0
        ):
            raise RuntimeError("failed solver turn artifacts are incomplete")

        status = _read_json_object(status_path, "failed solver turn status")
        attempts = status.get("attempts")
        retry_count = status.get("max_retries")
        common_attempt_boundary = (
            status.get("status") in {None, "failed"}
            and type(retry_count) is int
            and retry_count == self.config.agent.retries
            and isinstance(attempts, list)
            and bool(attempts)
            and status.get("attempt_count") == len(attempts)
            and all(
                isinstance(attempt, dict)
                and type(attempt.get("process_exit_code")) is int
                and attempt["process_exit_code"] == 0
                for attempt in attempts
            )
        )
        stream_retry_exhaustion = (
            common_attempt_boundary
            and len(attempts) == retry_count + 1
            and isinstance(attempts[-1].get("stream_errors"), list)
            and bool(attempts[-1]["stream_errors"])
        )
        validation_errors = status.get("validation_errors")
        excluded_cache_failure = (
            common_attempt_boundary
            and len(attempts) == 1
            and attempts[-1].get("stream_errors") == []
            and attempts[-1].get("output_errors") == []
            and isinstance(validation_errors, list)
            and len(validation_errors) == 1
            and isinstance(validation_errors[0], str)
            and validation_errors[0].startswith(
                "snapshot contains a non-regular file: "
            )
            and validation_errors[0].split(": ", 1)[1].split("/", 1)[0]
            in {".cache", ".uv-cache", ".uv_cache"}
        )
        interrupted_after_provider_success = (
            state.phase is _RevisionPhase.TURN_IN_PROGRESS
            and common_attempt_boundary
            and status.get("exit_code") == 0
            and attempts[-1].get("stream_errors") == []
            and attempts[-1].get("output_errors") == []
        )
        if not (
            stream_retry_exhaustion
            or excluded_cache_failure
            or interrupted_after_provider_success
        ):
            self._reset_uncertain_solver_turn(state, turn_dir, turn_index)
            return

        self._validate_submission_outputs(workspace)
        _solution_tree_sha256(workspace)
        submission_id = f"s{turn_index:03d}"
        if os.path.lexists(self.experiment_dir / "submissions" / submission_id):
            raise RuntimeError("failed solver turn already has a submission snapshot")
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
            state.session_id,
        )

        turn_dir.chmod(stat.S_IMODE(os.lstat(turn_dir).st_mode) | stat.S_IRWXU)
        status_path.chmod(
            stat.S_IMODE(os.lstat(status_path).st_mode) | stat.S_IRUSR | stat.S_IWUSR
        )
        transport_exit_code = status.get("transport_exit_code")
        if type(transport_exit_code) is not int:
            provider_exit_code = status.get("provider_exit_code")
            transport_exit_code = (
                provider_exit_code if type(provider_exit_code) is int else 1
            )
        recovery_status = (
            "accepted_after_retry_exhaustion"
            if stream_retry_exhaustion
            else "accepted_after_cache_exclusion"
            if excluded_cache_failure
            else "accepted_after_interrupted_boundary"
        )
        status.update(
            {
                "status": recovery_status,
                "exit_code": 0,
                "transport_exit_code": transport_exit_code,
                "accepted_after_retry_exhaustion": stream_retry_exhaustion,
                "recovered_on_resume": True,
            }
        )
        _write_json(status_path, status)
        _make_tree_read_only(turn_dir)
        state.submission_ids.append(submission_id)
        state.next_turn_index += 1
        state.phase = _RevisionPhase.READY_FOR_JUDGE
        self._write_state(state)
        self._append_event(
            {
                "event": "turn_recovered",
                "turn": turn_index,
                "session_id": state.session_id,
                "reason": (
                    "accepted workspace after stream retry exhaustion"
                    if stream_retry_exhaustion
                    else "accepted workspace after excluding disposable cache"
                    if excluded_cache_failure
                    else "accepted completed provider turn after interruption"
                ),
            }
        )

    def _reset_uncertain_solver_turn(
        self,
        state: _RevisionState,
        turn_dir: Path,
        turn_index: int,
    ) -> None:
        for path in (self.experiment_dir, turn_dir.parent, turn_dir):
            path.chmod(stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRWXU)
        archive_root = self.experiment_dir / "interrupted-turns"
        archive_root.mkdir(exist_ok=True)
        archive_root.chmod(
            stat.S_IMODE(os.lstat(archive_root).st_mode) | stat.S_IRWXU
        )
        archive = archive_root / f"turn-{turn_index:03d}"
        suffix = 1
        while os.path.lexists(archive):
            archive = archive_root / f"turn-{turn_index:03d}-{suffix:03d}"
            suffix += 1
        shutil.move(str(turn_dir), str(archive))
        state.phase = _RevisionPhase.READY_FOR_TURN
        self._write_state(state)
        self._append_event(
            {
                "event": "turn_reset_after_interruption",
                "turn": turn_index,
                "session_id": state.session_id,
                "archive": str(archive.relative_to(self.experiment_dir)),
            }
        )

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

        if state.session_id is None:
            turn = self.dependencies.session.start(
                workspace,
                state.next_prompt,
                turn_dir,
                on_session_id=record_early_session_id,
            )
            record_early_session_id(turn.session_id)
        else:
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
            mitigation=self.config.mitigation,
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
        write_revision_score_plot(
            state.scores,
            self.experiment_dir / "score_improvement.png",
            task_id=self.task_dir.name,
            feedback_policy=FeedbackPolicy(self.config.feedback_policy).value,
        )
        if self.config.publish_report:
            publish_revision_report(self.experiment_dir)
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
        expected_prompt = solver_prompt(self.config.mitigation)
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
                mitigation=self.config.mitigation,
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

    def _compact_historical_submissions(
        self, state: _RevisionState
    ) -> tuple[int, int]:
        """Drop bulky derived files from scored non-final submissions.

        Completed state is written first, so this deliberately idempotent operation
        can finish repairing both sides of an interrupted compaction during resume.
        """
        if state.phase is not _RevisionPhase.COMPLETED:
            raise RuntimeError("historical snapshots may only be compacted when complete")
        removed_files = 0
        removed_logical_bytes = 0
        for submission_id in state.submission_ids[:-1]:
            submission_removed_files = 0
            submission_removed_logical_bytes = 0
            submission_dir = self.experiment_dir / "submissions" / submission_id
            attempt_id = state.judge_attempts[submission_id]
            evaluation_workspace = (
                self.experiment_dir
                / "evaluations"
                / submission_id
                / self.rubric.sha256
                / attempt_id
                / "run"
                / "workspace"
            )
            # Custom judge implementations may keep their evaluation cache
            # outside the standard experiment tree. Standard staging is compacted
            # first so its tree continues to match the submission after both steps.
            if os.path.lexists(evaluation_workspace):
                _compact_historical_workspace(evaluation_workspace)
            stats = _compact_historical_workspace(submission_dir / "workspace")
            removed_files += stats.removed_files
            removed_logical_bytes += stats.removed_logical_bytes
            submission_removed_files += stats.removed_files
            submission_removed_logical_bytes += stats.removed_logical_bytes

            snapshot_path = submission_dir / "snapshot.json"
            snapshot = _read_json_object(snapshot_path, "submission snapshot")
            snapshot.update(
                {
                    "workspace_scope": "judge-inputs",
                    "workspace_sha256": _tree_sha256(submission_dir / "workspace"),
                    "historical_workspace_files_removed": snapshot.get(
                        "historical_workspace_files_removed", 0
                    )
                    + submission_removed_files,
                    "historical_workspace_logical_bytes_removed": snapshot.get(
                        "historical_workspace_logical_bytes_removed", 0
                    )
                    + submission_removed_logical_bytes,
                }
            )
            submission_dir.chmod(
                stat.S_IMODE(os.lstat(submission_dir).st_mode) | stat.S_IRWXU
            )
            if snapshot_path.exists():
                snapshot_path.chmod(
                    stat.S_IMODE(os.lstat(snapshot_path).st_mode) | stat.S_IWUSR
                )
            _write_json_atomic(snapshot_path, snapshot)
            _make_read_only(snapshot_path)
            _make_read_only(submission_dir)
        return removed_files, removed_logical_bytes

    def _persist_rubric(self) -> None:
        self.store.persist_rubric()

    def _verify_frozen_rubric(self) -> None:
        self.store.verify_frozen_rubric()

    def _write_state(self, state: _RevisionState) -> None:
        self.store.write_state(state)

    def _read_state(self) -> _RevisionState:
        return self.store.read_state()

    def _update_manifest(self, updates: dict[str, object]) -> None:
        self.store.update_manifest(updates)

    def _record_session_id(self, session_id: str) -> None:
        self.store.record_session_id(session_id)

    def _record_effective_solver_model(
        self, state: _RevisionState, model: str
    ) -> None:
        self.store.record_effective_solver_model(state, model)

    def _pin_or_verify_scoring_identity(self, validation_path: Path) -> None:
        self.store.verify_scoring_identity(validation_path)

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
        submissions_root = self.experiment_dir / "submissions"
        submissions_root.mkdir(exist_ok=True)
        previous_workspaces = sorted(
            path / "workspace"
            for path in submissions_root.iterdir()
            if path.is_dir() and path.name < submission_id
        )
        previous_workspace = previous_workspaces[-1] if previous_workspaces else None
        submission_dir.mkdir(parents=True)
        copy_stats = _copy_solution_workspace(
            workspace,
            snapshot_workspace,
            previous=previous_workspace,
        )
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
                "workspace_logical_bytes": copy_stats.logical_bytes,
                "workspace_copied_bytes": copy_stats.copied_bytes,
                "workspace_deduplicated_bytes": copy_stats.linked_bytes,
                "workspace_copied_files": copy_stats.copied_files,
                "workspace_deduplicated_files": copy_stats.linked_files,
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
                "workspace_logical_bytes": copy_stats.logical_bytes,
                "workspace_copied_bytes": copy_stats.copied_bytes,
                "workspace_deduplicated_bytes": copy_stats.linked_bytes,
            }
        )
        return submission_dir

    def _append_event(self, payload: dict[str, object]) -> None:
        self.store.append_event(payload)


def run_submission_revision(
    config: SubmissionRevisionConfig,
) -> SubmissionRevisionResult:
    return SubmissionRevisionController(config).run()
