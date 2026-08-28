"""Stateful controller for linear benchmark submission revision."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from tqdm.auto import trange

from rubric_gen.submission_revision.prompts import PromptProfile, solver_prompt
from rubric_gen.runtime.agents.workspaces import (
    TaskWorkspace,
    ensure_artifacts_dir,
)
from rubric_gen.runtime.progress import PROGRESS_BAR_FORMAT
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
    SubmissionRevisionResult,
)
from rubric_gen.submission_revision.controller_setup import build_revision_setup
from rubric_gen.submission_revision.controller_scoring import RevisionScorer
from rubric_gen.submission_revision.controller_recovery import RevisionRecovery
from rubric_gen.submission_revision.controller_workspace import (
    RevisionWorkspaceManager,
)
from rubric_gen.submission_revision.artifacts import (
    LIVE_ROOT_PREFIX as _LIVE_ROOT_PREFIX,
    live_root_parent as _live_root_parent,
    REVISION_EXPERIMENT_KIND as _REVISION_EXPERIMENT_KIND,
    read_json_object as _read_json_object,
    remove_created_live_tree as _remove_created_live_tree,
    remove_live_tree as _remove_tree,
    sha256_file as _sha256_file,
    solution_tree_sha256 as _solution_tree_sha256,
    write_json as _write_json,
    write_live_root_sentinel as _write_live_root_sentinel,
)
from rubric_gen.submission_revision.evolution import (
    rubric_generation_implementation_sha256,
)
from rubric_gen.submission_revision.rubric_bank import RubricBankPolicy


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
        *,
        judgment_reuse_root: Path | None = None,
    ) -> None:
        setup = build_revision_setup(
            config,
            dependencies,
            judgment_reuse_root,
        )
        self.config = config
        self.benchmark = setup.benchmark
        self.experiment_dir = setup.experiment_dir
        self.task_dir = setup.task_dir
        self.judgment_reuse = setup.judgment_reuse
        self.initial_rubric = setup.initial_rubric
        self.bank_policy = setup.bank_policy
        self.initial_bank = setup.initial_bank
        self.master_rubric = setup.master_rubric
        self.instruction_sha256 = setup.instruction_sha256
        self.data_sha256 = setup.data_sha256
        self.seed = setup.seed
        self.dependencies = setup.dependencies
        self.master_judge = setup.master_judge
        self.scoring_identity = setup.scoring_identity
        self.master_scoring_identity = setup.master_scoring_identity
        self.reuse_seed_judgment = setup.reuse_seed_judgment
        self.reuse_seed_master_judgment = setup.reuse_seed_master_judgment
        self.store = setup.store
        self.scoring = RevisionScorer(
            config=config,
            benchmark=self.benchmark,
            experiment_dir=self.experiment_dir,
            task_dir=self.task_dir,
            dependencies=self.dependencies,
            bank_policy=self.bank_policy,
            initial_bank=self.initial_bank,
            initial_rubric=self.initial_rubric,
            master_rubric=self.master_rubric,
            master_judge=self.master_judge,
            seed=self.seed,
            judgment_reuse=self.judgment_reuse,
            reuse_seed_judgment=self.reuse_seed_judgment,
            reuse_seed_master_judgment=self.reuse_seed_master_judgment,
            instruction_sha256=self.instruction_sha256,
            data_sha256=self.data_sha256,
            store=self.store,
        )
        self.workspaces = RevisionWorkspaceManager(
            config=config,
            benchmark=self.benchmark,
            experiment_dir=self.experiment_dir,
            task_dir=self.task_dir,
            seed=self.seed,
            scoring=self.scoring,
            instruction_sha256=self.instruction_sha256,
            store=self.store,
        )
        self.recovery = RevisionRecovery(
            config=config,
            experiment_dir=self.experiment_dir,
            task_dir=self.task_dir,
            dependencies=self.dependencies,
            bank_policy=self.bank_policy,
            scoring_identity=self.scoring_identity,
            seed=self.seed,
            store=self.store,
            scoring=self.scoring,
            workspaces=self.workspaces,
            experiment_identity=self._experiment_identity(),
        )

    def _experiment_identity(self) -> dict[str, object]:
        identity: dict[str, object] = {
            "experiment_id": self.config.experiment_id,
            "benchmark": str(self.config.benchmark),
            "assignment_id": self.config.assignment_id,
            "condition_id": self.config.condition_id,
            "replicate": self.config.replicate,
            "execution_order": self.config.execution_order,
            "task_id": self.task_dir.name,
            "task_dir": str(self.task_dir),
            "revision_rounds": self.config.revision_rounds,
            "provider": self.config.agent.provider,
            "model": self.config.agent.model,
            "executable": self.config.agent.executable,
            "isolation": "codex-custom-permission-profile",
            "command_network_access": False,
            "web_search": False,
            "reasoning_effort": self.config.agent.reasoning_effort,
            "service_tier": self.config.agent.service_tier,
            "solver_base_url": self.config.agent.base_url,
            "turn_timeout_seconds": self.config.agent.timeout_seconds,
            "feedback_policy": FeedbackPolicy(self.config.feedback_policy).value,
            "prompt": PromptProfile(self.config.prompt_profile).value,
            "rubric_policy": self.bank_policy.value,
            "rubric_proposer_model": self.config.rubric_proposer_model,
            "rubric_proposer_base_url": self.config.rubric_proposer_base_url,
            "rubric_proposer_max_retries": self.config.rubric_proposer_max_retries,
            "rubric_semantic_judge_model": (
                self.config.rubric_semantic_judge_model
            ),
            "rubric_semantic_judge_base_url": (
                self.config.rubric_semantic_judge_base_url
            ),
            "rubric_semantic_judge_max_calls": (
                self.config.rubric_semantic_judge_max_calls
            ),
            "rubric_semantic_judge_max_request_bytes": (
                self.config.rubric_semantic_judge_max_request_bytes
            ),
            "rubric_semantic_judge_max_output_tokens": (
                self.config.rubric_semantic_judge_max_output_tokens
            ),
            "rubric_generation_implementation_sha256": (
                rubric_generation_implementation_sha256()
            ),
            "review": self.config.review,
            "judge_model": self.config.judge_model,
            "judge_base_url": self.config.judge_base_url,
            "max_review_chars": self.config.max_review_chars,
            "initial_rubric_path": str(
                self.config.optimizer_rubric_path.resolve()
            ),
            "initial_bank_sha256": self.initial_bank.bank.content_sha256,
            "initial_bank_member_count": self.initial_bank.bank.rubric_count,
            "master_rubric_name": self.config.master_rubric_name,
            "master_rubric_sha256": self.master_rubric.sha256,
            "instruction_sha256": self.instruction_sha256,
            "data_sha256": self.data_sha256,
            "seed_run_dir": str(self.seed.root),
            "seed_sha256": self.seed.sha256,
        }
        if self.config.feedback_simulator is not None:
            identity["feedback_simulator"] = self.config.feedback_simulator.identity()
        return identity

    def run(self) -> SubmissionRevisionResult:
        initialized = False
        completed = False
        if self.config.resume:
            state, live_root, workspace = self.recovery.load_resume()
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
                phase=_RevisionPhase.READY_FOR_JUDGE,
                next_turn_index=1,
                session_id=None,
                effective_solver_model=None,
                submission_ids=["s000"],
                scores=[],
                fixed_original_scores=[],
                judge_attempts={},
                next_prompt=solver_prompt(
                    self.config.prompt_profile,
                    self.config.benchmark,
                ),
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
                    self.scoring.run_judge_boundary(state)
                if state.phase not in {
                    _RevisionPhase.READY_FOR_TURN,
                    _RevisionPhase.COMPLETED,
                }:
                    raise RuntimeError(f"invalid revision state: {state.phase}")
            self.scoring.validate_latest_boundary(state)
            state.phase = _RevisionPhase.COMPLETED
            self.store.write_state(state)
            compaction = self.workspaces.compact_historical_submissions(state)
            self.store.append_event(
                {
                    "event": "experiment_completed",
                    "session_id": state.session_id,
                    "submission_count": len(state.submission_ids),
                    "scores": state.scores,
                    "fixed_original_scores": state.fixed_original_scores,
                    "historical_workspace_files_removed": compaction[0],
                    "historical_workspace_logical_bytes_removed": compaction[1],
                }
            )
            self.scoring.publish_final_plot(
                state,
                state.submission_ids[-1],
            )
            completed = True
            return SubmissionRevisionResult(
                experiment_dir=self.experiment_dir,
                session_id=state.session_id or "",
                submission_ids=tuple(state.submission_ids),
                scores=tuple(state.scores),
                fixed_original_scores=tuple(state.fixed_original_scores),
            )
        finally:
            if completed or not initialized:
                _remove_tree(live_root, self.experiment_dir)
            if completed:
                self.store.update_manifest({"live_workspace_removed": True})

    def _initialize(
        self,
        workspace: Path,
        live_root: Path,
        state: _RevisionState,
    ) -> None:
        self.experiment_dir.mkdir(parents=True)
        TaskWorkspace(self.task_dir, workspace).create()
        self.workspaces.materialize_seed(workspace)
        self.workspaces.link_seed_snapshot()
        _write_json(
            self.experiment_dir / "manifest.json",
            {
                "kind": _REVISION_EXPERIMENT_KIND,
                **self._experiment_identity(),
                "submission_count": self.config.revision_rounds + 1,
                "live_workspace_dir": str(workspace),
                "live_workspace_removed": False,
                "session_id": None,
                "effective_solver_model": None,
                "initial_member_scoring_identity": self.scoring_identity,
            },
        )
        self.store.persist_initial_bank()
        self.store.write_state(state)
        if self.bank_policy is RubricBankPolicy.OFFLINE_ELICITATION:
            self.scoring.compile_offline_bank()

    def _run_solver_turn(self, state: _RevisionState, workspace: Path) -> None:
        ensure_artifacts_dir(workspace)
        turn_index = state.next_turn_index
        state.phase = _RevisionPhase.TURN_IN_PROGRESS
        self.store.write_state(state)
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
            self.store.record_session_id(session_id)
            self.store.write_state(state)

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
        self.store.record_effective_solver_model(state, turn.model)
        if turn.exit_code != 0:
            raise _SolverTurnFailure(
                f"provider exited with code {turn.exit_code}", turn.exit_code
            )
        try:
            self.workspaces.verify_live_instruction(workspace)
            self.workspaces.validate_submission_outputs(workspace)
            _solution_tree_sha256(workspace)
        except (OSError, RuntimeError) as exc:
            raise _SolverTurnFailure(str(exc), 2) from exc
        submission_id = f"s{turn_index:03d}"
        trajectories = [self.seed.submission_dir / "trajectory.stream.jsonl"] + [
            self.experiment_dir
            / "turns"
            / f"turn-{index:03d}"
            / "trajectory.stream.jsonl"
            for index in range(1, turn_index + 1)
        ]
        self.workspaces.snapshot_submission(
            submission_id,
            workspace,
            trajectories,
            state.session_id or "",
        )
        self.store.append_event(
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
        self.store.write_state(state)

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
        self.store.write_state(state)
        self.store.append_event(
            {
                "event": "turn_failed",
                "turn": turn_index,
                "exit_code": exit_code,
                "session_id": state.session_id,
                "reason": reason,
            }
        )

def run_submission_revision(
    config: SubmissionRevisionConfig,
    *,
    judgment_reuse_root: Path | None = None,
) -> SubmissionRevisionResult:
    return SubmissionRevisionController(
        config,
        judgment_reuse_root=judgment_reuse_root,
    ).run()
