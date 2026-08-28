"""Own live workspaces and sealed revision submissions."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic as _write_json_atomic
from rubric_gen.benchmarks import SubmissionBenchmark
from rubric_gen.runtime.agents.workspaces import TaskWorkspace
from rubric_gen.submission_revision.artifacts import (
    compact_historical_workspace as _compact_historical_workspace,
    copy_solution_workspace as _copy_solution_workspace,
    link_solution_workspace as _link_solution_workspace,
    make_read_only as _make_read_only,
    make_tree_owner_writable as _make_tree_owner_writable,
    make_tree_read_only as _make_tree_read_only,
    read_json_object as _read_json_object,
    sha256_file as _sha256_file,
    solution_tree_sha256 as _solution_tree_sha256,
    tree_sha256 as _tree_sha256,
    verify_submission_snapshot as _verify_submission_snapshot,
    write_json as _write_json,
)
from rubric_gen.submission_revision.controller_scoring import RevisionScorer
from rubric_gen.submission_revision.models import (
    RevisionPhase as _RevisionPhase,
    RevisionState as _RevisionState,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.seeds import ResolvedSeed
from rubric_gen.submission_revision.store import RevisionStore


class RevisionWorkspaceManager:
    def __init__(
        self,
        *,
        config: SubmissionRevisionConfig,
        benchmark: SubmissionBenchmark,
        experiment_dir: Path,
        task_dir: Path,
        seed: ResolvedSeed,
        scoring: RevisionScorer,
        instruction_sha256: str,
        store: RevisionStore,
    ) -> None:
        self.config = config
        self.benchmark = benchmark
        self.experiment_dir = experiment_dir
        self.task_dir = task_dir
        self.seed = seed
        self.scoring = scoring
        self.instruction_sha256 = instruction_sha256
        self.store = store

    def materialize_seed(self, workspace: Path) -> None:
        source = self.seed.submission_dir / "workspace"
        for child in source.iterdir():
            destination = workspace / child.name
            if destination.exists():
                raise RuntimeError(f"seed conflicts with task workspace: {child.name}")
            if child.is_dir():
                shutil.copytree(child, destination, copy_function=shutil.copyfile)
            else:
                shutil.copyfile(child, destination)
            _make_tree_owner_writable(destination)

    def link_seed_snapshot(self) -> None:
        source = self.seed.submission_dir
        destination = self.experiment_dir / "submissions" / "s000"
        destination.mkdir(parents=True)
        _link_solution_workspace(source / "workspace", destination / "workspace")
        os.link(source / "trajectory.stream.jsonl", destination / "trajectory.stream.jsonl")
        _write_json(
            destination / "status.json",
            {
                "task": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "workspace_dir": str(destination / "workspace"),
                "provider": self.config.agent.provider,
                "session_id": None,
                "submission_id": "s000",
                "exit_code": 0,
            },
        )
        shutil.copyfile(source / "snapshot.json", destination / "snapshot.json")
        _make_tree_read_only(destination)

    def restore_last_scored_workspace(
        self,
        state: _RevisionState,
        workspace: Path,
    ) -> None:
        restored = workspace.parent / "workspace-restore"
        if os.path.lexists(restored):
            raise RuntimeError(f"stale workspace restore path exists: {restored}")
        if state.submission_ids:
            source = (
                self.experiment_dir
                / "submissions"
                / state.submission_ids[-1]
                / "workspace"
            )
            _verify_submission_snapshot(source.parent)
            shutil.copytree(source, restored, copy_function=shutil.copyfile)
            _make_tree_owner_writable(restored)
            TaskWorkspace(self.task_dir, restored).restore_inputs()
        else:
            TaskWorkspace(self.task_dir, restored).create()
        _make_tree_owner_writable(workspace)
        shutil.rmtree(workspace)
        restored.rename(workspace)

    def verify_recovered_submission_snapshot(
        self,
        submission_dir: Path,
        workspace: Path,
        trajectories: list[Path],
        session_id: str,
    ) -> None:
        """Validate a snapshot sealed before an interrupted state update."""

        _verify_submission_snapshot(submission_dir)
        snapshot = _read_json_object(
            submission_dir / "snapshot.json", "recovered submission snapshot"
        )
        status = _read_json_object(
            submission_dir / "status.json", "recovered submission status"
        )
        if (
            snapshot.get("session_id") != session_id
            or snapshot.get("workspace_sha256") != _solution_tree_sha256(workspace)
            or status.get("task") != self.task_dir.name
            or status.get("task_dir") != str(self.task_dir)
            or status.get("workspace_dir") != str(submission_dir / "workspace")
            or status.get("provider") != self.config.agent.provider
            or status.get("session_id") != session_id
            or status.get("submission_id") != submission_dir.name
            or status.get("exit_code") != 0
        ):
            raise RuntimeError(
                "existing recovered submission snapshot disagrees with the solver turn"
            )
        expected_trajectory = hashlib.sha256()
        for trajectory in trajectories:
            raw = trajectory.read_bytes()
            expected_trajectory.update(raw)
            if raw and not raw.endswith(b"\n"):
                expected_trajectory.update(b"\n")
        if snapshot.get("trajectory_sha256") != expected_trajectory.hexdigest():
            raise RuntimeError(
                "existing recovered submission trajectory disagrees with the solver turn"
            )

    def compact_historical_submissions(
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
        retained_names = self.benchmark.retained_workspace_names
        for submission_id in state.submission_ids[:-1]:
            submission_removed_files = 0
            submission_removed_logical_bytes = 0
            submission_dir = self.experiment_dir / "submissions" / submission_id
            attempt_id = state.judge_attempts[submission_id]
            submission_index = int(submission_id[1:])
            bank = self.scoring.active_bank_generation(submission_index).bank
            for item in bank.items:
                evaluation_workspace = (
                    self.experiment_dir
                    / "evaluations"
                    / submission_id
                    / item.rubric.content_sha256
                    / attempt_id
                    / "run"
                    / "workspace"
                )
                # Custom judges can keep caches outside the standard tree.
                if os.path.lexists(evaluation_workspace):
                    _compact_historical_workspace(
                        evaluation_workspace,
                        retained_names=retained_names,
                    )
            stats = _compact_historical_workspace(
                submission_dir / "workspace",
                retained_names=retained_names,
            )
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

    def validate_submission_outputs(self, workspace: Path) -> None:
        errors = self.benchmark.output_errors(workspace)
        if errors:
            raise RuntimeError(
                "solver submission is missing or has invalid required outputs: "
                + ", ".join(errors)
            )

    def verify_live_instruction(self, workspace: Path) -> None:
        if _sha256_file(workspace / "instruction.md") != self.instruction_sha256:
            raise RuntimeError("solver modified the task instruction")

    def snapshot_submission(
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
        self.store.append_event(
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


