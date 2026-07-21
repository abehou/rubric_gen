"""Judge target discovery and run-layout validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .artifacts import JudgeArtifactStore
from .models import JudgeRunConfig, JudgeTarget


_SAFE_TASK_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class JudgeTargetDiscovery:
    """Discover judge targets and bind their directory identities."""

    def __init__(self, config: JudgeRunConfig, artifacts: JudgeArtifactStore) -> None:
        self.config = config
        self.artifacts = artifacts

    def validated_task_id(self, task: object) -> str:
        if type(task) is not str or _SAFE_TASK_COMPONENT.fullmatch(task) is None:
            raise SystemExit(f"Invalid judge task ID: {task!r}")
        return task

    def canonical_task_dir(
        self,
        task: object,
        status_task_dir: object | None = None,
    ) -> Path:
        task_id = self.validated_task_id(task)
        configured = self.config.tasks_dir.expanduser() / task_id
        if configured.is_symlink() or not configured.is_dir():
            raise SystemExit(f"Missing regular configured task directory: {configured}")
        try:
            canonical = configured.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid configured task directory: {configured}") from exc
        if status_task_dir is not None:
            if type(status_task_dir) is not str:
                raise SystemExit("status task_dir must be a path string")
            status_path = Path(status_task_dir).expanduser()
            if status_path.is_symlink():
                raise SystemExit(
                    f"status task directory must not be a symlink: {status_path}"
                )
            try:
                status_canonical = status_path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise SystemExit(f"Invalid status task directory: {status_path}") from exc
            if status_canonical != canonical:
                raise SystemExit(
                    "status task directory disagrees with configured task directory: "
                    f"{status_path}"
                )
        return canonical

    def validated_workspace(
        self,
        workspace: Path,
        *,
        expected: Path | tuple[Path, ...],
    ) -> Path:
        if workspace.is_symlink():
            raise SystemExit(f"workspace directory must not be a symlink: {workspace}")
        try:
            canonical = workspace.expanduser().resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid workspace directory: {workspace}") from exc
        expected_paths = expected if isinstance(expected, tuple) else (expected,)
        expected_canonical = {
            path.expanduser().resolve(strict=False) for path in expected_paths
        }
        if canonical not in expected_canonical:
            raise SystemExit(
                f"status workspace directory disagrees with run layout: {workspace}"
            )
        return canonical

    @staticmethod
    def standalone_workspace_options(run_dir: Path) -> tuple[Path, ...]:
        expected = run_dir.parent / "_workspaces" / run_dir.name
        legacy = run_dir / "workspace"
        if expected.exists() or expected.is_symlink():
            return (expected,)
        if legacy.exists() or legacy.is_symlink():
            return (legacy,)
        return (expected,)

    def validate_target_identity(self, target: JudgeTarget) -> None:
        canonical_task_dir = self.canonical_task_dir(target.task)
        if target.task_dir.is_symlink():
            raise SystemExit(
                f"target task directory must not be a symlink: {target.task_dir}"
            )
        try:
            target_task_dir = target.task_dir.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid target task directory: {target.task_dir}") from exc
        if target_task_dir != canonical_task_dir:
            raise SystemExit(
                "target task directory disagrees with configured task directory: "
                f"{target.task_dir}"
            )
        if target.run_dir.is_symlink() or not target.run_dir.is_dir():
            raise SystemExit(
                f"run directory must be a regular directory: {target.run_dir}"
            )
        if target.run_dir.parent.name == "tasks":
            expected_workspace = target.run_dir.parents[1] / "workspaces" / target.task
            self.validated_workspace(target.workspace_dir, expected=expected_workspace)
        else:
            self.validated_workspace(
                target.workspace_dir,
                expected=self.standalone_workspace_options(target.run_dir),
            )
        expected_trajectory = (target.run_dir / "trajectory.stream.jsonl").absolute()
        if target.trajectory_path.expanduser().absolute() != expected_trajectory:
            raise SystemExit(
                f"trajectory path disagrees with run layout: {target.trajectory_path}"
            )
        current = self.artifacts.snapshot_target_identities(target)
        self.artifacts.bind_target_identities(target, current)

    def discover_targets(self) -> list[JudgeTarget]:
        targets: list[JudgeTarget] = []
        canonical_run_dirs: dict[Path, Path] = {}
        for run_dir in self.config.run_dirs:
            try:
                canonical_run_dir = run_dir.expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise SystemExit(f"Invalid judge run directory: {run_dir}") from exc
            if canonical_run_dir in canonical_run_dirs:
                raise SystemExit(
                    "Duplicate canonical run directory: "
                    f"{run_dir} aliases {canonical_run_dirs[canonical_run_dir]}"
                )
            canonical_run_dirs[canonical_run_dir] = run_dir
            batch = self._read_json(run_dir / "batch.json")
            manifest = self._read_json(run_dir / "manifest.json")
            if batch.get("kind") == "rubric-gen-submission-revision-batch":
                targets.extend(self._discover_revision_batch(run_dir, batch))
            elif manifest.get("kind") == "rubric-gen-submission-revision-experiment":
                targets.append(self._discover_revision_experiment(run_dir, manifest))
            elif (run_dir / "tasks").is_dir() and (run_dir / "workspaces").is_dir():
                targets.extend(self._discover_batch_targets(run_dir))
            else:
                targets.append(self._discover_single_target(run_dir))
        canonical_target_runs: dict[tuple[int, int], Path] = {}
        for target in targets:
            self.validate_target_identity(target)
            identities = self.artifacts.target_identities(target)
            assert identities is not None
            if identities.run in canonical_target_runs:
                raise SystemExit(
                    "Duplicate canonical target run directory: "
                    f"{target.run_dir} aliases {canonical_target_runs[identities.run]}"
                )
            canonical_target_runs[identities.run] = target.run_dir
        if self.config.limit is not None:
            targets = targets[: self.config.limit]
        return targets

    def _discover_revision_batch(
        self, batch_dir: Path, batch: dict[str, object]
    ) -> list[JudgeTarget]:
        raw_experiments = batch.get("experiment_dirs")
        if type(raw_experiments) is not list or any(
            type(value) is not str for value in raw_experiments
        ):
            raise SystemExit("revision batch has invalid experiment_dirs")
        targets: list[JudgeTarget] = []
        for relative_value in raw_experiments:
            relative = Path(relative_value)
            if relative.is_absolute() or ".." in relative.parts:
                raise SystemExit("revision batch experiment path is unsafe")
            experiment = batch_dir / relative
            manifest = self._read_json(experiment / "manifest.json")
            if manifest.get("kind") != "rubric-gen-submission-revision-experiment":
                raise SystemExit(f"invalid revision experiment: {experiment}")
            targets.append(self._discover_revision_experiment(experiment, manifest))
        return targets

    def _discover_revision_experiment(
        self, experiment_dir: Path, manifest: dict[str, object]
    ) -> JudgeTarget:
        state = self._read_json(experiment_dir / "state.json")
        submissions = state.get("submission_ids")
        task = manifest.get("task_id")
        if (
            type(submissions) is not list
            or not submissions
            or any(type(value) is not str for value in submissions)
        ):
            raise SystemExit(f"revision experiment has no submissions: {experiment_dir}")
        task_id = self.validated_task_id(task)
        submission = experiment_dir / "submissions" / submissions[-1]
        task_dir = self.canonical_task_dir(task_id, manifest.get("task_dir"))
        return JudgeTarget(
            task=task_id,
            task_dir=task_dir,
            run_dir=submission,
            workspace_dir=submission / "workspace",
            trajectory_path=submission / "trajectory.stream.jsonl",
            output_root=experiment_dir,
        )

    def _discover_batch_targets(self, batch_dir: Path) -> list[JudgeTarget]:
        targets: list[JudgeTarget] = []
        tasks_root = batch_dir / "tasks"
        workspaces_root = batch_dir / "workspaces"
        if tasks_root.is_symlink() or workspaces_root.is_symlink():
            raise SystemExit(
                f"Batch run layout must not contain symlink roots: {batch_dir}"
            )
        for task_run_dir in sorted(tasks_root.iterdir()):
            if task_run_dir.is_symlink():
                raise SystemExit(
                    f"Task run directory must not be a symlink: {task_run_dir}"
                )
            if not task_run_dir.is_dir():
                continue
            task = self.validated_task_id(task_run_dir.name)
            status = self._read_json(task_run_dir / "status.json")
            if status.get("task") is not None and status["task"] != task:
                raise SystemExit(
                    f"status task disagrees with task run directory: {task_run_dir}"
                )
            task_dir = self.canonical_task_dir(task, status.get("task_dir"))
            expected_workspace = workspaces_root / task
            raw_workspace = status.get("workspace_dir")
            if raw_workspace is not None and type(raw_workspace) is not str:
                raise SystemExit("status workspace_dir must be a path string")
            workspace_dir = self.validated_workspace(
                Path(raw_workspace) if raw_workspace is not None else expected_workspace,
                expected=expected_workspace,
            )
            targets.append(
                JudgeTarget(
                    task=task,
                    task_dir=task_dir,
                    run_dir=task_run_dir,
                    workspace_dir=workspace_dir,
                    trajectory_path=task_run_dir / "trajectory.stream.jsonl",
                    output_root=batch_dir,
                )
            )
        return targets

    def _discover_single_target(self, run_dir: Path) -> JudgeTarget:
        status = self._read_json(run_dir / "status.json")
        task = self.validated_task_id(status.get("task") or self._infer_task_name(run_dir))
        if run_dir.parent.name == "tasks" and task != run_dir.name:
            raise SystemExit(f"status task disagrees with task run directory: {run_dir}")
        if run_dir.name.startswith("da-") and task != self._infer_task_name(run_dir):
            raise SystemExit(
                f"status task disagrees with run directory identity: {run_dir}"
            )
        task_dir = self.canonical_task_dir(task, status.get("task_dir"))
        workspace = status.get("workspace_dir")
        if workspace is None and run_dir.parent.name == "tasks":
            workspace = run_dir.parents[1] / "workspaces" / task
        if workspace is None:
            workspace = self.standalone_workspace_options(run_dir)[0]
        if type(workspace) is not str and not isinstance(workspace, Path):
            raise SystemExit("status workspace_dir must be a path string")
        workspace_path = Path(workspace)
        if run_dir.parent.name == "tasks":
            workspace_path = self.validated_workspace(
                workspace_path,
                expected=run_dir.parents[1] / "workspaces" / task,
            )
        else:
            workspace_path = self.validated_workspace(
                workspace_path,
                expected=self.standalone_workspace_options(run_dir),
            )
        return JudgeTarget(
            task=task,
            task_dir=task_dir,
            run_dir=run_dir,
            workspace_dir=workspace_path,
            trajectory_path=run_dir / "trajectory.stream.jsonl",
            output_root=run_dir,
        )

    @staticmethod
    def _infer_task_name(run_dir: Path) -> str:
        parts = run_dir.name.split("-")
        for index in range(len(parts) - 2):
            if (
                parts[index].startswith("da")
                and parts[index + 1].isdigit()
                and parts[index + 2].isdigit()
            ):
                return "-".join(parts[index : index + 3])
        if run_dir.name.startswith("da-"):
            return run_dir.name
        raise SystemExit(f"Could not infer task name from run directory: {run_dir}")

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}
