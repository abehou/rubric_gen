"""Resume and recover interrupted submission revisions."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic as _write_json_atomic
from rubric_gen.submission_revision.artifacts import (
    LIVE_ROOT_PREFIX as _LIVE_ROOT_PREFIX,
    is_excluded_solution_root as _is_excluded_solution_root,
    live_root_parent as _live_root_parent,
    read_json_object as _read_json_object,
    remove_created_live_tree as _remove_created_live_tree,
    remove_live_tree as _remove_tree,
    revision_manifest_keys as _revision_manifest_keys,
    solution_tree_sha256 as _solution_tree_sha256,
    validate_live_root as _validate_live_root,
    verify_submission_snapshot as _verify_submission_snapshot,
    write_json as _write_json,
    write_live_root_sentinel as _write_live_root_sentinel,
)
from rubric_gen.submission_revision.controller_recovery_artifacts import (
    numbered_bank_directories,
    remove_owned_rubric_generation_residue,
    rubric_generation_entries,
)
from rubric_gen.submission_revision.controller_scoring import RevisionScorer
from rubric_gen.submission_revision.controller_workspace import RevisionWorkspaceManager
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.rubric_bank import RubricBankPolicy
from rubric_gen.submission_revision.rubric_bank_lifecycle import (
    load_rubric_bank,
    persist_rubric_bank,
)
from rubric_gen.submission_revision.seeds import ResolvedSeed
from rubric_gen.submission_revision.store import RevisionStore


@dataclass(frozen=True)
class _FailedTurnBoundary:
    turn_index: int
    turn_dir: Path
    status_path: Path
    trajectory_path: Path


class _RecoveryDisposition(Enum):
    RESET = auto()
    DISPOSABLE_EXCLUSION = auto()
    PROVIDER_COMPLETED = auto()


class RevisionRecovery:
    def __init__(
        self,
        *,
        config: SubmissionRevisionConfig,
        experiment_dir: Path,
        task_dir: Path,
        dependencies: RevisionDependencies,
        bank_policy: RubricBankPolicy,
        scoring_identity: dict[str, object],
        seed: ResolvedSeed,
        store: RevisionStore,
        scoring: RevisionScorer,
        workspaces: RevisionWorkspaceManager,
        experiment_identity: dict[str, object],
    ) -> None:
        self.config = config
        self.experiment_dir = experiment_dir
        self.task_dir = task_dir
        self.dependencies = dependencies
        self.bank_policy = bank_policy
        self.scoring_identity = scoring_identity
        self.seed = seed
        self.store = store
        self.scoring = scoring
        self.workspaces = workspaces
        self.experiment_identity = experiment_identity

    def load_resume(self) -> tuple[_RevisionState, Path, Path]:
        if not self.experiment_dir.is_dir():
            raise FileNotFoundError(
                f"experiment directory does not exist: {self.experiment_dir}"
            )
        manifest = _read_json_object(
            self.experiment_dir / "manifest.json",
            "revision manifest",
        )
        if set(manifest) != _revision_manifest_keys(self.config.feedback_policy.value):
            raise RuntimeError("revision manifest has invalid fields")
        for key, value in self.experiment_identity.items():
            if manifest.get(key) != value:
                raise RuntimeError(f"resume configuration changed: {key}")
        if manifest.get("initial_member_scoring_identity") != self.scoring_identity:
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
        self.store.verify_initial_bank()
        self.scoring.verify_canonical_task_inputs()
        state = self.store.read_state()
        if state.phase is _RevisionPhase.COMPLETED:
            self.workspaces.compact_historical_submissions(state)
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
                and len(state.submission_ids)
                == len(state.scores)
                == len(state.fixed_original_scores)
                == total
            ):
                self._validate_resume_state(state, None, manifest)
                return state, live_root, workspace
            if workspace.is_symlink():
                raise RuntimeError(
                    f"live revision workspace is an invalid symlink: {workspace}"
                )
            live_root, workspace = self._rebuild_live_workspace(
                state, live_root, manifest
            )
        self.workspaces.verify_live_instruction(workspace)
        if state.phase in {
            _RevisionPhase.FAILED_TURN,
            _RevisionPhase.TURN_IN_PROGRESS,
        }:
            self._recover_failed_solver_boundary(state, workspace, manifest)
        self._validate_resume_state(state, workspace, manifest)
        return state, live_root, workspace

    def _rebuild_live_workspace(
        self,
        state: _RevisionState,
        old_live_root: Path,
        manifest: dict[str, object],
    ) -> tuple[Path, Path]:
        if os.path.lexists(old_live_root):
            _validate_live_root(old_live_root, self.experiment_dir)
            _remove_tree(old_live_root, self.experiment_dir)
        live_root = Path(
            tempfile.mkdtemp(prefix=_LIVE_ROOT_PREFIX, dir=_live_root_parent())
        )
        try:
            _write_live_root_sentinel(live_root, self.experiment_dir)
            workspace = live_root / "workspace"
            workspace.mkdir()
            self.workspaces.restore_last_scored_workspace(state, workspace)
            self.workspaces.verify_live_instruction(workspace)
            manifest["live_workspace_dir"] = str(workspace)
            manifest["live_workspace_removed"] = False
            self._discard_solver_session(
                state,
                manifest,
                reason="live workspace was rebuilt from a sealed submission",
            )
        except BaseException:
            _remove_created_live_tree(live_root)
            raise
        self.store.append_event(
            {
                "event": "live_workspace_rebuilt",
                "submission_id": (
                    state.submission_ids[-1] if state.submission_ids else None
                ),
            }
        )
        return live_root, workspace

    def _discard_solver_session(
        self,
        state: _RevisionState,
        manifest: dict[str, object],
        *,
        reason: str,
    ) -> None:
        previous_session_id = state.session_id
        state.session_id = None
        state.effective_solver_model = None
        manifest["session_id"] = None
        manifest["effective_solver_model"] = None
        _write_json_atomic(self.experiment_dir / "manifest.json", manifest)
        self.store.write_state(state)
        if previous_session_id is not None:
            self.store.append_event(
                {
                    "event": "solver_session_discarded",
                    "session_id": previous_session_id,
                    "reason": reason,
                }
            )

    def _recover_failed_solver_boundary(
        self,
        state: _RevisionState,
        workspace: Path,
        manifest: dict[str, object],
    ) -> None:
        """Recover a solver interruption from the last sealed boundary."""

        boundary = self._failed_turn_boundary(state)
        if self._recover_unfinalized_turn(state, workspace, manifest, boundary):
            return
        self._validate_solver_identity(state, manifest)
        controlled_reason = self._controlled_failure_reason(state, boundary)
        if controlled_reason is not None:
            self._restore_reset_and_discard(
                state,
                workspace,
                manifest,
                boundary,
                controlled_reason,
            )
            return
        self._validate_turn_artifacts(boundary)
        status = _read_json_object(
            boundary.status_path,
            "failed solver turn status",
        )
        disposition = self._recovery_disposition(state, workspace, status)
        if disposition is _RecoveryDisposition.RESET:
            self._restore_reset_and_discard(
                state,
                workspace,
                manifest,
                boundary,
                "solver turn output was not safe to resume",
            )
            return
        self._promote_recovered_turn(
            state,
            workspace,
            boundary,
            status,
            disposition,
        )

    def _failed_turn_boundary(self, state: _RevisionState) -> _FailedTurnBoundary:
        turn_index = state.next_turn_index
        if not 0 <= turn_index < self.config.revision_rounds + 1:
            raise RuntimeError("failed revision state has an invalid turn index")
        expected_ids = [f"s{index:03d}" for index in range(turn_index)]
        if (
            state.submission_ids != expected_ids
            or len(state.scores) != turn_index
            or len(state.fixed_original_scores) != turn_index
            or set(state.judge_attempts) != set(state.submission_ids)
        ):
            raise RuntimeError("failed revision state boundary counts are inconsistent")
        self.scoring.validate_latest_boundary(state)
        turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
        expected_turns = [
            self.experiment_dir / "turns" / f"turn-{index:03d}"
            for index in range(1, turn_index + 1)
        ]
        if sorted((self.experiment_dir / "turns").glob("turn-*")) != expected_turns:
            raise RuntimeError("experiment contains an uncertain failed solver turn")
        prompt_path = turn_dir / "prompt.txt"
        if (
            prompt_path.is_symlink()
            or not prompt_path.is_file()
            or prompt_path.read_text() != state.next_prompt
        ):
            raise RuntimeError(
                "failed revision state prompt disagrees with the executed turn"
            )
        return _FailedTurnBoundary(
            turn_index=turn_index,
            turn_dir=turn_dir,
            status_path=turn_dir / "status.json",
            trajectory_path=turn_dir / "trajectory.stream.jsonl",
        )

    @staticmethod
    def _unfinalized_turn_layout(
        state: _RevisionState,
        boundary: _FailedTurnBoundary,
    ) -> bool:
        turn_dir = boundary.turn_dir
        attempts = turn_dir / "attempts"
        return (
            state.phase is _RevisionPhase.TURN_IN_PROGRESS
            and boundary.turn_index > 0
            and not os.path.lexists(boundary.status_path)
            and not os.path.lexists(boundary.trajectory_path)
            and not turn_dir.is_symlink()
            and turn_dir.is_dir()
            and {path.name for path in turn_dir.iterdir()}
            in ({"prompt.txt"}, {"attempts", "prompt.txt"})
            and (
                not os.path.lexists(attempts)
                or not attempts.is_symlink() and attempts.is_dir()
            )
        )

    def _recover_unfinalized_turn(
        self,
        state: _RevisionState,
        workspace: Path,
        manifest: dict[str, object],
        boundary: _FailedTurnBoundary,
    ) -> bool:
        if not self._unfinalized_turn_layout(state, boundary):
            return False
        if (
            manifest.get("session_id") != state.session_id
            or manifest.get("effective_solver_model")
            != state.effective_solver_model
        ):
            raise RuntimeError(
                "interrupted revision state has inconsistent solver identity"
            )
        self._restore_reset_and_discard(
            state,
            workspace,
            manifest,
            boundary,
            "solver interrupted before finalizing turn artifacts",
        )
        return True

    @staticmethod
    def _validate_solver_identity(
        state: _RevisionState,
        manifest: dict[str, object],
    ) -> None:
        if (
            (state.session_id is None) != (state.effective_solver_model is None)
            or manifest.get("session_id") != state.session_id
            or manifest.get("effective_solver_model")
            != state.effective_solver_model
        ):
            raise RuntimeError("failed revision state has inconsistent solver identity")

    @staticmethod
    def _controlled_failure_reason(
        state: _RevisionState,
        boundary: _FailedTurnBoundary,
    ) -> str | None:
        if (
            state.phase is not _RevisionPhase.FAILED_TURN
            or os.path.lexists(boundary.trajectory_path)
            or boundary.turn_dir.is_symlink()
            or not boundary.turn_dir.is_dir()
            or boundary.status_path.is_symlink()
            or not boundary.status_path.is_file()
        ):
            return None
        status = _read_json_object(
            boundary.status_path,
            "failed solver turn status",
        )
        errors = tuple(status.get("validation_errors") or ())
        controlled = {
            ("controlled Codex configuration changed",),
            ("codex did not report a session ID during resume",),
        }
        if (
            status.get("status") != "failed"
            or status.get("exit_code") != 1
            or errors not in controlled
        ):
            return None
        return errors[0]

    def _restore_reset_and_discard(
        self,
        state: _RevisionState,
        workspace: Path,
        manifest: dict[str, object],
        boundary: _FailedTurnBoundary,
        reason: str,
    ) -> None:
        self.workspaces.restore_last_scored_workspace(state, workspace)
        self._discard_solver_session(state, manifest, reason=reason)
        self._reset_uncertain_solver_turn(
            state,
            boundary.turn_dir,
            boundary.turn_index,
        )

    @staticmethod
    def _validate_turn_artifacts(boundary: _FailedTurnBoundary) -> None:
        if (
            boundary.turn_dir.is_symlink()
            or not boundary.turn_dir.is_dir()
            or boundary.status_path.is_symlink()
            or not boundary.status_path.is_file()
            or boundary.trajectory_path.is_symlink()
            or not boundary.trajectory_path.is_file()
            or boundary.trajectory_path.stat().st_size == 0
        ):
            raise RuntimeError("failed solver turn artifacts are incomplete")

    def _completed_attempts(
        self,
        status: dict[str, object],
    ) -> tuple[dict[str, object], ...]:
        attempts = status.get("attempts")
        if (
            status.get("status") not in {None, "failed"}
            or status.get("max_retries") != self.config.agent.retries
            or not isinstance(attempts, list)
            or not attempts
            or status.get("attempt_count") != len(attempts)
            or any(
                not isinstance(attempt, dict)
                or type(attempt.get("process_exit_code")) is not int
                or attempt["process_exit_code"] != 0
                for attempt in attempts
            )
        ):
            return ()
        return tuple(attempt for attempt in attempts if isinstance(attempt, dict))

    def _recovery_disposition(
        self,
        state: _RevisionState,
        workspace: Path,
        status: dict[str, object],
    ) -> _RecoveryDisposition:
        attempts = self._completed_attempts(status)
        if not attempts:
            return _RecoveryDisposition.RESET
        validation_errors = status.get("validation_errors")
        excluded_root = (
            len(attempts) == 1
            and attempts[-1].get("stream_errors") == []
            and attempts[-1].get("output_errors") == []
            and isinstance(validation_errors, list)
            and len(validation_errors) == 1
            and isinstance(validation_errors[0], str)
            and validation_errors[0].startswith(
                "snapshot contains a non-regular file: "
            )
            and _is_excluded_solution_root(
                workspace
                / validation_errors[0].split(": ", 1)[1].split("/", 1)[0]
            )
        )
        if excluded_root:
            return _RecoveryDisposition.DISPOSABLE_EXCLUSION
        provider_completed = (
            state.phase is _RevisionPhase.TURN_IN_PROGRESS
            and status.get("exit_code") == 0
            and attempts[-1].get("stream_errors") == []
            and attempts[-1].get("output_errors") == []
        )
        return (
            _RecoveryDisposition.PROVIDER_COMPLETED
            if provider_completed
            else _RecoveryDisposition.RESET
        )

    def _promote_recovered_turn(
        self,
        state: _RevisionState,
        workspace: Path,
        boundary: _FailedTurnBoundary,
        status: dict[str, object],
        disposition: _RecoveryDisposition,
    ) -> None:
        if type(state.session_id) is not str or not state.session_id:
            raise RuntimeError("recovered solver turn has no session ID")
        self.workspaces.validate_submission_outputs(workspace)
        _solution_tree_sha256(workspace)
        submission_id = f"s{boundary.turn_index:03d}"
        submission_dir = self.experiment_dir / "submissions" / submission_id
        trajectories = [self.seed.submission_dir / "trajectory.stream.jsonl"] + [
            self.experiment_dir
            / "turns"
            / f"turn-{index:03d}"
            / "trajectory.stream.jsonl"
            for index in range(1, boundary.turn_index + 1)
        ]
        if os.path.lexists(submission_dir):
            self.workspaces.verify_recovered_submission_snapshot(
                submission_dir,
                workspace,
                trajectories,
                state.session_id,
            )
        else:
            self.workspaces.snapshot_submission(
                submission_id,
                workspace,
                trajectories,
                state.session_id,
            )
        self._seal_recovered_turn(state, boundary, status, disposition, submission_id)

    def _seal_recovered_turn(
        self,
        state: _RevisionState,
        boundary: _FailedTurnBoundary,
        status: dict[str, object],
        disposition: _RecoveryDisposition,
        submission_id: str,
    ) -> None:
        boundary.turn_dir.chmod(
            stat.S_IMODE(os.lstat(boundary.turn_dir).st_mode) | stat.S_IRWXU
        )
        boundary.status_path.chmod(
            stat.S_IMODE(os.lstat(boundary.status_path).st_mode)
            | stat.S_IRUSR
            | stat.S_IWUSR
        )
        transport_exit_code = status.get("transport_exit_code")
        if type(transport_exit_code) is not int:
            provider_exit_code = status.get("provider_exit_code")
            transport_exit_code = (
                provider_exit_code if type(provider_exit_code) is int else 1
            )
        excluded = disposition is _RecoveryDisposition.DISPOSABLE_EXCLUSION
        status.update({
            "status": (
                "accepted_after_disposable_exclusion"
                if excluded
                else "accepted_after_interrupted_boundary"
            ),
            "exit_code": 0,
            "transport_exit_code": transport_exit_code,
            "recovered_on_resume": True,
        })
        _write_json(boundary.status_path, status)
        state.submission_ids.append(submission_id)
        state.next_turn_index += 1
        state.phase = _RevisionPhase.READY_FOR_JUDGE
        self.store.write_state(state)
        self.store.append_event({
            "event": "turn_recovered",
            "turn": boundary.turn_index,
            "session_id": state.session_id,
            "reason": (
                "accepted workspace after excluding disposable run state"
                if excluded
                else "accepted completed provider turn after interruption"
            ),
        })

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
        self.store.write_state(state)
        self.store.append_event(
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
                and len(state.fixed_original_scores) == state.next_turn_index - 1
            )
        else:
            valid_counts = (
                len(state.submission_ids)
                == len(state.scores)
                == len(state.fixed_original_scores)
                == state.next_turn_index
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
        if (state.session_id is None) != (state.effective_solver_model is None):
            raise RuntimeError("revision state has partial solver identity")
        if manifest.get("session_id") != state.session_id:
            raise RuntimeError("manifest and revision state disagree on session ID")
        if manifest.get("effective_solver_model") != state.effective_solver_model:
            raise RuntimeError("manifest and revision state disagree on solver model")
        turn_dirs = sorted((self.experiment_dir / "turns").glob("turn-*"))
        expected_turns = [
            self.experiment_dir / "turns" / f"turn-{index:03d}"
            for index in range(1, state.next_turn_index)
        ]
        if turn_dirs != expected_turns:
            raise RuntimeError("experiment contains an uncertain solver turn")
        if len(state.submission_ids) > len(state.scores):
            submission_id = state.submission_ids[-1]
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
        self._validate_rubric_generation_replay()
        self.scoring.validate_latest_boundary(state)
        if manifest.get("initial_member_scoring_identity") != self.scoring_identity:
            raise RuntimeError("revision manifest has the wrong scoring identity")

    def _validate_rubric_generation_replay(self) -> None:
        """Replay every sealed proposal before any resumed dispatch."""

        proposal_root = self.experiment_dir / "rubric-generations"
        bank_root = self.experiment_dir / "rubric-banks"
        if self.bank_policy is RubricBankPolicy.FIXED:
            if os.path.lexists(proposal_root):
                raise RuntimeError("a fixed policy cannot contain rubric generations")
            if numbered_bank_directories(
                bank_root,
                required=True,
                context="rubric bank",
            ) != [0]:
                raise RuntimeError("a fixed policy can contain only bank round 0")
            return

        maximum_generation = (
            1
            if self.bank_policy is RubricBankPolicy.OFFLINE_ELICITATION
            else self.config.revision_rounds - 1
        )
        remove_owned_rubric_generation_residue(
            proposal_root,
            max_generation_round=maximum_generation,
        )
        proposal_rounds = rubric_generation_entries(proposal_root)
        bank_rounds = numbered_bank_directories(
            bank_root,
            required=True,
            context="rubric bank",
        )
        if (
            self.bank_policy is RubricBankPolicy.OFFLINE_ELICITATION
            and bank_rounds == [0]
            and not proposal_rounds
        ):
            self.scoring.compile_offline_bank()
            proposal_rounds = rubric_generation_entries(proposal_root)
            bank_rounds = numbered_bank_directories(
                bank_root,
                required=True,
                context="rubric bank",
            )
        if not bank_rounds or bank_rounds[0] != 0:
            raise RuntimeError("rubric bank generations must start at round 0")
        elicitation_rounds = bank_rounds[1:]
        if elicitation_rounds != list(range(1, len(elicitation_rounds) + 1)):
            raise RuntimeError("rubric elicitation generations are not contiguous")
        if proposal_rounds != list(range(1, len(proposal_rounds) + 1)):
            raise RuntimeError("rubric proposal generations are not contiguous")
        if proposal_rounds[: len(elicitation_rounds)] != elicitation_rounds:
            raise RuntimeError(
                "a persisted rubric bank has no matching sealed proposal"
            )
        if len(proposal_rounds) not in {
            len(elicitation_rounds),
            len(elicitation_rounds) + 1,
        }:
            raise RuntimeError(
                "sealed rubric proposals are more than one bank ahead"
            )
        if proposal_rounds and proposal_rounds[-1] > maximum_generation:
            raise RuntimeError("rubric elicitation generation exceeds the study length")
        proposer = self.dependencies.bank_proposer
        if proposer is None:
            raise RuntimeError("elicitation replay has no rubric proposer")
        instruction = (self.task_dir / "instruction.md").read_text(
            encoding="utf-8"
        )
        for generation_round in proposal_rounds:
            prior = load_rubric_bank(
                self.experiment_dir,
                generation_round - 1,
                expected_policy=self.bank_policy,
            )
            replayed = proposer.elicit_rubric(
                instruction=instruction,
                current_bank=prior.bank,
                policy=self.bank_policy,
                generation_round=generation_round,
                output_dir=proposal_root,
                    artifact_history=self.scoring.elicitation_history(
                        generation_round
                    ),
                source_boundary=(
                    generation_round
                    if self.bank_policy is RubricBankPolicy.ONLINE_ELICITATION
                    else None
                ),
            )
            if generation_round <= len(elicitation_rounds):
                persisted = load_rubric_bank(
                    self.experiment_dir,
                    generation_round,
                    expected_policy=self.bank_policy,
                )
                if replayed != persisted:
                    raise RuntimeError(
                        "rubric generation disagrees with the persisted bank"
                    )
            else:
                persist_rubric_bank(
                    self.experiment_dir,
                    replayed,
                    self.bank_policy,
                )
