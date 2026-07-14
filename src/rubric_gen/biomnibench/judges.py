"""Run BiomniBench task judges over saved agent runs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from statistics import pstdev
from threading import Lock
from typing import Any, Iterator

from rubric_gen.biomnibench.common import TerminalProgress, resolve_project_path
from rubric_gen.biomnibench.rubric_scoring import (
    JudgeScoreValidationError,
    RUBRIC_SCORER_VERSION,
    parse_rubric_levels_strict,
    validate_judge_score,
)
from rubric_gen.biomnibench.rubric_bundles import (
    RubricBundleError,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.task_rubrics import canonical_json, load_json_strict

DEFAULT_JUDGE_MODEL = "gemini-3.1-pro-preview"
SCORE_VALIDATION_SCHEMA_VERSION = 1
SCORE_INPUT_ATTESTATION_KEYS = {
    "schema_version",
    "scorer_version",
    "review_input_sha256",
    "answer_input_sha256",
    "judge_source_sha256",
    "judge_runner_sha256",
    "scorer_module_sha256",
    "effective_judge_model",
    "review_mode",
    "max_review_chars",
    "task",
    "run_identity",
    "repeat_index",
}
SCORE_VALIDATION_KEYS = {
    "score",
    "raw_score",
    "reported_score",
    "score_matches_reported",
    "selected_levels",
    "criterion_scores",
    "rubric_source",
    "rubric_set_id",
    "rubric_id",
    "structured_rubric_sha256",
    "rendered_rubric_sha256",
    "manifest_sha256",
    "reward_sha256",
    "evaluation_sha256",
} | SCORE_INPUT_ATTESTATION_KEYS
_SAFE_TASK_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def _safe_basename(value: object, context: str) -> str:
    if (
        type(value) is not str
        or not value
        or value in {".", ".."}
        or Path(value).is_absolute()
        or Path(value).name != value
        or "/" in value
        or "\\" in value
        or "\x00" in value
    ):
        raise ValueError(f"{context} must be a safe basename")
    return value


@dataclass(frozen=True)
class ResolvedRubric:
    text: str
    path: Path
    structured_rubric_sha256: str | None
    rendered_rubric_sha256: str
    rubric_id: str | None
    rubric_set_id: str | None
    source: str
    manifest_path: Path | None
    manifest_sha256: str | None


@dataclass(frozen=True)
class JudgeRunConfig:
    run_dir: Path
    tasks_dir: Path
    extra_run_dirs: tuple[Path, ...] = ()
    review: str = "trace"
    model: str | None = None
    output_path: Path | None = None
    judge_name: str | None = None
    rubric_name: str | None = None
    rubric_set: Path | None = None
    limit: int | None = None
    dry_run: bool = False
    max_review_chars: int | None = None
    resume: bool = False
    force: bool = False
    max_concurrency: int = 1
    repeats: int = 1

    def __post_init__(self) -> None:
        if self.rubric_name is not None and self.rubric_set is not None:
            raise ValueError("rubric_name and rubric_set are mutually exclusive")
        if self.judge_name is not None:
            _safe_basename(self.judge_name, "judge_name")
        if self.rubric_name is not None:
            _safe_basename(self.rubric_name, "rubric_name")

    @classmethod
    def from_namespace(cls, args: Any) -> "JudgeRunConfig":
        output = getattr(args, "output", None)
        run_dir_args = getattr(args, "run_dir")
        raw_run_dirs = []
        for item in run_dir_args if isinstance(run_dir_args, list) else [run_dir_args]:
            if isinstance(item, list):
                raw_run_dirs.extend(item)
            else:
                raw_run_dirs.append(item)
        run_dirs = tuple(resolve_project_path(run_dir) for run_dir in raw_run_dirs)
        return cls(
            run_dir=run_dirs[0],
            tasks_dir=resolve_project_path(getattr(args, "tasks_dir")),
            extra_run_dirs=run_dirs[1:],
            review=getattr(args, "review", "trace"),
            model=getattr(args, "model", None),
            output_path=resolve_project_path(output) if output else None,
            judge_name=getattr(args, "judge_name", None),
            rubric_name=getattr(args, "rubric", None),
            rubric_set=(
                resolve_project_path(getattr(args, "rubric_set"))
                if getattr(args, "rubric_set", None)
                else None
            ),
            limit=getattr(args, "limit", None),
            dry_run=getattr(args, "dry_run", False),
            max_review_chars=getattr(args, "max_review_chars", None),
            resume=getattr(args, "resume", False),
            force=getattr(args, "force", False),
            max_concurrency=max(1, getattr(args, "max_concurrency", 1)),
            repeats=max(1, getattr(args, "repeats", 1)),
        )

    @property
    def run_dirs(self) -> tuple[Path, ...]:
        return (self.run_dir, *self.extra_run_dirs)


@dataclass(frozen=True)
class JudgeTarget:
    task: str
    task_dir: Path
    run_dir: Path
    workspace_dir: Path
    trajectory_path: Path
    output_root: Path


@dataclass(frozen=True)
class JudgeAttempt:
    target: JudgeTarget
    repeat_index: int

    @property
    def label(self) -> str:
        return f"{self.target.task}#{self.repeat_index}"


@dataclass(frozen=True)
class _OpenOutputDirectory:
    root_path: Path
    root_fd: int
    root_identity: tuple[int, int]
    path: Path
    fd: int


@dataclass(frozen=True)
class _TargetDirectoryIdentities:
    run: tuple[int, int]
    workspace: tuple[int, int]
    output_root: tuple[int, int]
    canonical_run: str


class BiomniBenchJudgeRunner:
    def __init__(self, config: JudgeRunConfig) -> None:
        self.config = config
        self._identity_lock = Lock()
        self._target_identities: dict[JudgeTarget, _TargetDirectoryIdentities] = {}

    @property
    def scores_path(self) -> Path:
        if self.config.output_path is not None:
            return self.config.output_path
        return self.config.run_dir / f"judge-{self.config.review}-scores.json"

    @property
    def summary_path(self) -> Path:
        return self.scores_path

    def _validated_task_id(self, task: object) -> str:
        if type(task) is not str or _SAFE_TASK_COMPONENT.fullmatch(task) is None:
            raise SystemExit(f"Invalid judge task ID: {task!r}")
        return task

    def _canonical_task_dir(
        self,
        task: object,
        status_task_dir: object | None = None,
    ) -> Path:
        task_id = self._validated_task_id(task)
        configured = self.config.tasks_dir.expanduser() / task_id
        if configured.is_symlink() or not configured.is_dir():
            raise SystemExit(f"Missing regular configured task directory: {configured}")
        try:
            canonical = configured.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemExit(
                f"Invalid configured task directory: {configured}"
            ) from exc
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
                raise SystemExit(
                    f"Invalid status task directory: {status_path}"
                ) from exc
            if status_canonical != canonical:
                raise SystemExit(
                    f"status task directory disagrees with configured task directory: {status_path}"
                )
        return canonical

    def _validated_workspace(
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

    def _standalone_workspace_options(self, run_dir: Path) -> tuple[Path, ...]:
        expected = run_dir.parent / "_workspaces" / run_dir.name
        legacy = run_dir / "workspace"
        if expected.exists() or expected.is_symlink():
            return (expected,)
        if legacy.exists() or legacy.is_symlink():
            return (legacy,)
        return (expected,)

    def validate_target_identity(self, target: JudgeTarget) -> None:
        canonical_task_dir = self._canonical_task_dir(target.task)
        if target.task_dir.is_symlink():
            raise SystemExit(
                f"target task directory must not be a symlink: {target.task_dir}"
            )
        try:
            target_task_dir = target.task_dir.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SystemExit(
                f"Invalid target task directory: {target.task_dir}"
            ) from exc
        if target_task_dir != canonical_task_dir:
            raise SystemExit(
                f"target task directory disagrees with configured task directory: {target.task_dir}"
            )
        if target.run_dir.is_symlink() or not target.run_dir.is_dir():
            raise SystemExit(
                f"run directory must be a regular directory: {target.run_dir}"
            )
        if target.run_dir.parent.name == "tasks":
            expected_workspace = target.run_dir.parents[1] / "workspaces" / target.task
            self._validated_workspace(target.workspace_dir, expected=expected_workspace)
        else:
            self._validated_workspace(
                target.workspace_dir,
                expected=self._standalone_workspace_options(target.run_dir),
            )
        expected_trajectory = (target.run_dir / "trajectory.stream.jsonl").absolute()
        if target.trajectory_path.expanduser().absolute() != expected_trajectory:
            raise SystemExit(
                f"trajectory path disagrees with run layout: {target.trajectory_path}"
            )
        current_identities = self._snapshot_target_directory_identities(target)
        self._bind_target_directory_identities(target, current_identities)

    def _snapshot_target_directory_identities(
        self,
        target: JudgeTarget,
    ) -> _TargetDirectoryIdentities:
        entries = (
            ("Target run directory", target.run_dir.expanduser().absolute()),
            (
                "Target workspace directory",
                target.workspace_dir.expanduser().absolute(),
            ),
            ("Target output root", target.output_root.expanduser().absolute()),
        )
        opened: list[tuple[str, Path, int]] = []
        try:
            for context, path in entries:
                opened.append((context, path, self._open_directory_fd(path, context)))
            for context, path, fd in opened:
                self._validate_directory_fd(fd, path, context)
            try:
                canonical_run = target.run_dir.expanduser().resolve(strict=True)
                canonical_run_stat = os.stat(canonical_run, follow_symlinks=False)
            except (OSError, RuntimeError) as exc:
                raise SystemExit(
                    f"Target run directory identity changed: {target.run_dir}"
                ) from exc
            run_identity = self._directory_fd_identity(opened[0][2])
            if (
                not stat.S_ISDIR(canonical_run_stat.st_mode)
                or (canonical_run_stat.st_dev, canonical_run_stat.st_ino)
                != run_identity
            ):
                raise SystemExit(
                    f"Target run directory identity changed: {target.run_dir}"
                )
            return _TargetDirectoryIdentities(
                run=run_identity,
                workspace=self._directory_fd_identity(opened[1][2]),
                output_root=self._directory_fd_identity(opened[2][2]),
                canonical_run=str(canonical_run),
            )
        finally:
            for _, _, fd in reversed(opened):
                os.close(fd)

    def _bind_target_directory_identities(
        self,
        target: JudgeTarget,
        current: _TargetDirectoryIdentities,
    ) -> None:
        with self._identity_lock:
            expected = self._target_identities.get(target)
            if expected is None:
                self._target_identities[target] = current
                return
        for label, path, expected_value, current_value in (
            ("run", target.run_dir, expected.run, current.run),
            ("workspace", target.workspace_dir, expected.workspace, current.workspace),
            (
                "output root",
                target.output_root,
                expected.output_root,
                current.output_root,
            ),
        ):
            if current_value != expected_value:
                raise SystemExit(f"Target {label} directory identity changed: {path}")
        if current.canonical_run != expected.canonical_run:
            raise SystemExit(f"Target run directory identity changed: {target.run_dir}")

    def _target_directory_identities(
        self,
        target: JudgeTarget,
    ) -> _TargetDirectoryIdentities:
        with self._identity_lock:
            identities = self._target_identities.get(target)
        if identities is None:
            self.validate_target_identity(target)
            with self._identity_lock:
                identities = self._target_identities[target]
        return identities

    def discover_targets(self) -> list[JudgeTarget]:
        targets = []
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
            if (run_dir / "tasks").is_dir() and (run_dir / "workspaces").is_dir():
                targets.extend(self._discover_batch_targets(run_dir))
            else:
                targets.append(self._discover_single_target(run_dir))
        canonical_target_runs: dict[tuple[int, int], Path] = {}
        for target in targets:
            self.validate_target_identity(target)
            run_identity = self._target_directory_identities(target).run
            if run_identity in canonical_target_runs:
                raise SystemExit(
                    "Duplicate canonical target run directory: "
                    f"{target.run_dir} aliases {canonical_target_runs[run_identity]}"
                )
            canonical_target_runs[run_identity] = target.run_dir
        if self.config.limit is not None:
            targets = targets[: self.config.limit]
        return targets

    def _discover_batch_targets(self, batch_dir: Path) -> list[JudgeTarget]:
        targets = []
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
            task = self._validated_task_id(task_run_dir.name)
            status = self._read_json(task_run_dir / "status.json")
            if status.get("task") is not None and status["task"] != task:
                raise SystemExit(
                    f"status task disagrees with task run directory: {task_run_dir}"
                )
            task_dir = self._canonical_task_dir(task, status.get("task_dir"))
            expected_workspace = workspaces_root / task
            raw_workspace = status.get("workspace_dir")
            if raw_workspace is not None and type(raw_workspace) is not str:
                raise SystemExit("status workspace_dir must be a path string")
            workspace_dir = self._validated_workspace(
                Path(raw_workspace)
                if raw_workspace is not None
                else expected_workspace,
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
        task = self._validated_task_id(
            status.get("task") or self._infer_task_name(run_dir)
        )
        if run_dir.parent.name == "tasks" and task != run_dir.name:
            raise SystemExit(
                f"status task disagrees with task run directory: {run_dir}"
            )
        if run_dir.name.startswith("da-") and task != self._infer_task_name(run_dir):
            raise SystemExit(
                f"status task disagrees with run directory identity: {run_dir}"
            )
        task_dir = self._canonical_task_dir(task, status.get("task_dir"))
        workspace = status.get("workspace_dir")
        if workspace is None and run_dir.parent.name == "tasks":
            workspace = run_dir.parents[1] / "workspaces" / task
        if workspace is None:
            workspace = self._standalone_workspace_options(run_dir)[0]
        if type(workspace) is not str and not isinstance(workspace, Path):
            raise SystemExit("status workspace_dir must be a path string")
        workspace_path = Path(workspace)
        if run_dir.parent.name == "tasks":
            workspace_path = self._validated_workspace(
                workspace_path,
                expected=run_dir.parents[1] / "workspaces" / task,
            )
        else:
            workspace_path = self._validated_workspace(
                workspace_path,
                expected=self._standalone_workspace_options(run_dir),
            )
        return JudgeTarget(
            task=task,
            task_dir=task_dir,
            run_dir=run_dir,
            workspace_dir=workspace_path,
            trajectory_path=run_dir / "trajectory.stream.jsonl",
            output_root=run_dir,
        )

    def _infer_task_name(self, run_dir: Path) -> str:
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

    def run(self) -> int:
        targets = self.discover_targets()
        attempts = [
            JudgeAttempt(target=target, repeat_index=repeat_index)
            for target in targets
            for repeat_index in range(1, self.repeat_count + 1)
        ]
        self.scores_path.parent.mkdir(parents=True, exist_ok=True)
        overall_exit = 0
        records = []
        with JudgeProgress(
            review=self.config.review,
            total=len(attempts),
        ) as progress:
            if self.job_count == 1:
                for index, attempt in enumerate(attempts, start=1):
                    record = self.review_attempt(attempt, index, progress)
                    records.append(record)
                    if record.get("exit_code", 0) != 0:
                        overall_exit = int(record["exit_code"])
            else:
                with ThreadPoolExecutor(max_workers=self.job_count) as executor:
                    futures = {
                        executor.submit(
                            self.review_attempt_without_progress, attempt
                        ): attempt
                        for attempt in attempts
                    }
                    for index, future in enumerate(as_completed(futures), start=1):
                        attempt = futures[future]
                        record = future.result()
                        records.append(record)
                        progress.record(
                            index,
                            attempt.label,
                            record.get("status", "completed"),
                            record,
                        )
                        progress.update()
                        if record.get("exit_code", 0) != 0:
                            overall_exit = int(record["exit_code"])

        summary = self.score_summary(records)
        self.scores_path.write_text(json.dumps(summary, indent=2) + "\n")
        self.print_score_summary(summary)
        print(f"Wrote judge scores: {self.scores_path}")
        return overall_exit

    @property
    def job_count(self) -> int:
        return max(1, self.config.max_concurrency)

    @property
    def repeat_count(self) -> int:
        return max(1, self.config.repeats)

    def review_attempt(
        self, attempt: JudgeAttempt, index: int, progress: "JudgeProgress"
    ) -> dict[str, Any]:
        completed = self.completed_record(attempt)
        if completed is not None:
            progress.record(index, attempt.label, "skipped", completed)
            progress.update()
            return completed

        progress.record(index, attempt.label, "started", {})
        record = self.review_target(attempt.target, attempt.repeat_index)
        progress.record(index, attempt.label, record.get("status", "completed"), record)
        progress.update()
        return record

    def review_attempt_without_progress(self, attempt: JudgeAttempt) -> dict[str, Any]:
        completed = self.completed_record(attempt)
        if completed is not None:
            return completed
        return self.review_target(attempt.target, attempt.repeat_index)

    def score_summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        by_task: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            task = str(record.get("task"))
            by_task.setdefault(task, []).append(record)

        tasks = []
        scores = []
        for task, task_records in sorted(by_task.items()):
            task_records = sorted(
                task_records, key=lambda item: int(item.get("repeat_index") or 1)
            )
            task_scores = [
                record["score"]
                for record in task_records
                if record.get("status") in {"completed", "skipped"}
                and type(record.get("score")) is int
            ]
            scores.extend(task_scores)
            first = task_records[0]
            tasks.append(
                {
                    "task": task,
                    "status": self.combined_status(task_records),
                    "score": task_scores[0]
                    if len(task_records) == 1 and task_scores
                    else None,
                    "scores": task_scores,
                    "mean_score": round(sum(task_scores) / len(task_scores), 4)
                    if task_scores
                    else None,
                    "score_stddev": round(pstdev(task_scores), 4)
                    if len(task_scores) > 1
                    else 0.0
                    if task_scores
                    else None,
                    "min_score": min(task_scores) if task_scores else None,
                    "max_score": max(task_scores) if task_scores else None,
                    "scored_repeats": len(task_scores),
                    "total_repeats": len(task_records),
                    "output_dir": first.get("output_dir"),
                    "reward": first.get("reward"),
                    "evaluation": first.get("evaluation"),
                    "stdout": first.get("stdout"),
                    "attempts": task_records,
                }
            )
        average = round(sum(scores) / len(scores), 4) if scores else None
        return {
            "review": self.config.review,
            "repeats": self.repeat_count,
            "max_concurrency": self.job_count,
            "total_tasks": len(tasks),
            "total_attempts": len(records),
            "scored_tasks": sum(1 for task in tasks if task["scored_repeats"] > 0),
            "scored_attempts": len(scores),
            "average_score": average,
            "score_stddev": round(pstdev(scores), 4)
            if len(scores) > 1
            else 0.0
            if scores
            else None,
            "tasks": tasks,
        }

    def combined_status(self, records: list[dict[str, Any]]) -> str:
        statuses = {record.get("status") for record in records}
        if statuses == {"skipped"}:
            return "skipped"
        if "failed" in statuses:
            return "failed"
        if "planned" in statuses:
            return "planned"
        if "completed" in statuses:
            return "completed"
        return str(records[-1].get("status") or "unknown")

    def print_score_summary(self, summary: dict[str, Any]) -> None:
        print(f"Judge scores ({summary['review']})")
        print("task\tstatus\tmean\tstddev\tscores")
        for task in summary["tasks"]:
            mean = task["mean_score"] if task["mean_score"] is not None else "-"
            stddev = task["score_stddev"] if task["score_stddev"] is not None else "-"
            scores = (
                ",".join(str(score) for score in task["scores"])
                if task["scores"]
                else "-"
            )
            print(f"{task['task']}\t{task['status']}\t{mean}\t{stddev}\t{scores}")
        average = summary["average_score"]
        if average is None:
            print(f"Average score: - (0/{summary['total_attempts']} scored attempts)")
        else:
            print(
                f"Average score: {average} "
                f"({summary['scored_attempts']}/{summary['total_attempts']} scored attempts)"
            )

    def completed_record(self, attempt: JudgeAttempt) -> dict[str, Any] | None:
        if not self.config.resume or self.config.force or self.config.dry_run:
            return None
        target = attempt.target
        output_dir = self.output_dir(target, attempt.repeat_index)
        reward_path = output_dir / "reward.json"
        evaluation_path = output_dir / "evaluation.json"
        score_validation_path = output_dir / "score_validation.json"
        rubric = self.resolve_rubric(target)
        judge_path = self.find_judge(target.task_dir)
        try:
            review_text, answer_text = self.review_inputs(target)
            judge_source = judge_path.read_bytes()
        except (OSError, UnicodeError):
            return None
        score_input_attestation = self.score_input_attestation(
            attempt=attempt,
            judge_source=judge_source,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=self.judge_model(os.environ.copy()),
        )
        if not output_dir.exists():
            return None
        identities = self._target_directory_identities(target)
        try:
            with self._open_output_directory(
                target.output_root,
                output_dir,
                expected_root_identity=identities.output_root,
                create=False,
            ) as output:
                validation = self.valid_score_validation(
                    rubric,
                    score_input_attestation,
                    output=output,
                )
        except FileNotFoundError:
            return None
        if validation is None:
            return None
        return {
            "task": target.task,
            "review": self.config.review,
            "repeat_index": attempt.repeat_index,
            "repeats": self.repeat_count,
            "run_dir": str(target.run_dir),
            "workspace_dir": str(target.workspace_dir),
            "trajectory": str(target.trajectory_path),
            "output_dir": str(output_dir),
            "status": "skipped",
            "exit_code": 0,
            "judge_exit_code": 0,
            "score": validation["score"],
            "reward": str(reward_path),
            "evaluation": str(evaluation_path),
            "stdout": str(output_dir / "stdout.txt"),
            "score_validation": str(score_validation_path),
            **self.rubric_record(rubric),
        }

    def review_target(
        self, target: JudgeTarget, repeat_index: int = 1
    ) -> dict[str, Any]:
        rubric = self.resolve_rubric(target)
        judge_path = self.find_judge(target.task_dir)
        output_dir = self.output_dir(target, repeat_index)

        review_text, answer_text = self.review_inputs(target)

        base_record = {
            "task": target.task,
            "review": self.config.review,
            "repeat_index": repeat_index,
            "repeats": self.repeat_count,
            "run_dir": str(target.run_dir),
            "workspace_dir": str(target.workspace_dir),
            "trajectory": str(target.trajectory_path),
            "judge": str(judge_path),
            "output_dir": str(output_dir),
            **self.rubric_record(rubric),
        }
        if self.config.dry_run:
            return {**base_record, "status": "planned", "exit_code": 0}

        identities = self._target_directory_identities(target)
        with self._open_output_directory(
            target.output_root,
            output_dir,
            expected_root_identity=identities.output_root,
        ) as output:
            self._write_output_text(output, "judge_input_trace.md", review_text)
            self._write_output_text(output, "judge_input_answer.txt", answer_text)
            result = self._execute_judge_with_output(
                judge_path,
                rubric,
                output,
                review_text,
                answer_text,
                attempt=JudgeAttempt(target, repeat_index),
            )
        return {**base_record, **result}

    def output_dir(self, target: JudgeTarget, repeat_index: int = 1) -> Path:
        self._validated_task_id(target.task)
        base = target.output_root / "judges" / self.config.review / target.task
        if self.repeat_count == 1:
            return self._safe_output_path(target.output_root, base)
        return self._safe_output_path(
            target.output_root,
            base / f"repeat-{repeat_index:02d}",
        )

    def _safe_output_path(self, output_root: Path, candidate: Path) -> Path:
        root = output_root.expanduser().absolute()
        path = candidate.expanduser().absolute()
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise SystemExit(f"Judge output leaves output root: {candidate}") from exc
        current = root
        if current.is_symlink():
            raise SystemExit(f"Judge output root must not be a symlink: {current}")
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise SystemExit(f"Judge output path contains a symlink: {current}")
        try:
            if not path.resolve(strict=False).is_relative_to(
                root.resolve(strict=False)
            ):
                raise SystemExit(f"Judge output leaves output root: {candidate}")
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid judge output path: {candidate}") from exc
        return path

    def _directory_open_flags(self) -> int:
        return (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )

    def _directory_fd_identity(self, fd: int) -> tuple[int, int]:
        value = os.fstat(fd)
        return value.st_dev, value.st_ino

    def _validate_directory_fd(
        self,
        fd: int,
        path: Path,
        context: str,
        expected_identity: tuple[int, int] | None = None,
    ) -> None:
        try:
            fd_stat = os.fstat(fd)
            path_stat = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise SystemExit(f"{context} path identity changed: {path}") from exc
        if (
            not stat.S_ISDIR(fd_stat.st_mode)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (fd_stat.st_dev, fd_stat.st_ino) != (path_stat.st_dev, path_stat.st_ino)
            or (
                expected_identity is not None
                and (fd_stat.st_dev, fd_stat.st_ino) != expected_identity
            )
        ):
            raise SystemExit(f"{context} path identity changed: {path}")

    def _open_directory_fd(self, path: Path, context: str) -> int:
        try:
            fd = os.open(path, self._directory_open_flags())
        except OSError as exc:
            raise SystemExit(
                f"{context} must be a stable regular directory: {path}"
            ) from exc
        try:
            self._validate_directory_fd(fd, path, context)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def _open_output_directory(
        self,
        output_root: Path,
        output_dir: Path,
        *,
        expected_root_identity: tuple[int, int],
        create: bool = True,
    ) -> Iterator[_OpenOutputDirectory]:
        path = self._safe_output_path(output_root, output_dir)
        root = output_root.expanduser().absolute()
        relative = path.relative_to(root)
        root_fd = self._open_directory_fd(root, "Judge output root")
        current_fd: int | None = None
        current_path = root
        try:
            self._validate_directory_fd(
                root_fd,
                root,
                "Judge output root",
                expected_root_identity,
            )
            current_fd = os.dup(root_fd)
            for part in relative.parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o755, dir_fd=current_fd)
                    except FileExistsError:
                        pass
                    except OSError as exc:
                        raise SystemExit(
                            "Could not create judge output directory component: "
                            f"{current_path / part}"
                        ) from exc
                try:
                    next_fd = os.open(
                        part,
                        self._directory_open_flags(),
                        dir_fd=current_fd,
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    raise SystemExit(
                        f"Judge output directory component is unsafe: {current_path / part}"
                    )
                except OSError as exc:
                    raise SystemExit(
                        f"Judge output directory component is unsafe: {current_path / part}"
                    ) from exc
                os.close(current_fd)
                current_fd = next_fd
                current_path = current_path / part
                self._validate_directory_fd(
                    current_fd,
                    current_path,
                    "Judge output directory",
                )

            output = _OpenOutputDirectory(
                root_path=root,
                root_fd=root_fd,
                root_identity=expected_root_identity,
                path=path,
                fd=current_fd,
            )
            self._safe_output_path(root, path)
            self._validate_output_directory(output)
            try:
                yield output
            finally:
                self._validate_output_directory(output)
        finally:
            if current_fd is not None:
                os.close(current_fd)
            os.close(root_fd)

    def _validate_output_directory(self, output: _OpenOutputDirectory) -> None:
        self._validate_directory_fd(
            output.root_fd,
            output.root_path,
            "Judge output root",
            output.root_identity,
        )
        self._validate_directory_fd(
            output.fd,
            output.path,
            "Judge output directory",
        )

    def _read_output_bytes(
        self,
        output: _OpenOutputDirectory,
        name: str,
    ) -> bytes:
        _safe_basename(name, "judge output filename")
        self._validate_output_directory(output)
        file_fd: int | None = None
        try:
            file_fd = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=output.fd,
            )
            before = os.fstat(file_fd)
            named_before = os.stat(
                name,
                dir_fd=output.fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(named_before.st_mode)
                or (before.st_dev, before.st_ino)
                != (named_before.st_dev, named_before.st_ino)
            ):
                raise JudgeScoreValidationError(
                    f"cached judge output is not a stable regular file: {name}"
                )

            chunks: list[bytes] = []
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(file_fd)
            named_after = os.stat(
                name,
                dir_fd=output.fd,
                follow_symlinks=False,
            )
            if (
                self._stable_artifact_signature(before)
                != self._stable_artifact_signature(after)
                or not stat.S_ISREG(named_after.st_mode)
                or (after.st_dev, after.st_ino)
                != (named_after.st_dev, named_after.st_ino)
            ):
                raise JudgeScoreValidationError(
                    f"cached judge output changed while being read: {name}"
                )
            return b"".join(chunks)
        finally:
            if file_fd is not None:
                os.close(file_fd)
            self._validate_output_directory(output)

    def _write_output_text(
        self,
        output: _OpenOutputDirectory,
        name: str,
        text: str,
    ) -> None:
        self._write_output_bytes(output, name, text.encode("utf-8"))

    def _write_output_bytes(
        self,
        output: _OpenOutputDirectory,
        name: str,
        payload: bytes,
    ) -> None:
        _safe_basename(name, "judge output filename")
        self._validate_output_directory(output)
        token = secrets.token_hex(12)
        temporary_name = f".{name}.{token}.tmp"
        backup_name = f".{name}.{token}.bak"
        temporary_exists = False
        backup_exists = False
        target_committed = False
        succeeded = False
        fd: int | None = None
        try:
            fd = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=output.fd,
            )
            temporary_exists = True
            remaining = memoryview(payload)
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("short write to judge output")
                remaining = remaining[written:]
            os.close(fd)
            fd = None
            self._validate_output_directory(output)
            try:
                os.replace(
                    name,
                    backup_name,
                    src_dir_fd=output.fd,
                    dst_dir_fd=output.fd,
                )
                backup_exists = True
            except FileNotFoundError:
                pass
            self._validate_output_directory(output)
            os.replace(
                temporary_name,
                name,
                src_dir_fd=output.fd,
                dst_dir_fd=output.fd,
            )
            temporary_exists = False
            target_committed = True
            self._validate_output_directory(output)
            if backup_exists:
                os.unlink(backup_name, dir_fd=output.fd)
                backup_exists = False
                self._validate_output_directory(output)
            succeeded = True
        except OSError as exc:
            raise SystemExit(
                f"Could not write judge output file: {output.path / name}"
            ) from exc
        finally:
            if fd is not None:
                os.close(fd)
            if not succeeded and target_committed:
                try:
                    os.unlink(name, dir_fd=output.fd)
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            if not succeeded and backup_exists:
                try:
                    os.replace(
                        backup_name,
                        name,
                        src_dir_fd=output.fd,
                        dst_dir_fd=output.fd,
                    )
                    backup_exists = False
                except OSError:
                    pass
            if temporary_exists:
                try:
                    os.unlink(temporary_name, dir_fd=output.fd)
                except FileNotFoundError:
                    pass
            if backup_exists:
                try:
                    os.unlink(backup_name, dir_fd=output.fd)
                except FileNotFoundError:
                    pass

    def _unlink_output_file(
        self,
        output: _OpenOutputDirectory,
        name: str,
    ) -> None:
        _safe_basename(name, "judge output filename")
        self._validate_output_directory(output)
        tombstone_name = f".{name}.{secrets.token_hex(12)}.stale"
        tombstone_exists = False
        succeeded = False
        try:
            os.replace(
                name,
                tombstone_name,
                src_dir_fd=output.fd,
                dst_dir_fd=output.fd,
            )
            tombstone_exists = True
        except FileNotFoundError:
            self._validate_output_directory(output)
            return
        except OSError as exc:
            raise SystemExit(
                f"Could not remove stale judge output: {output.path / name}"
            ) from exc
        try:
            self._validate_output_directory(output)
            os.unlink(tombstone_name, dir_fd=output.fd)
            tombstone_exists = False
            self._validate_output_directory(output)
            succeeded = True
        except OSError as exc:
            raise SystemExit(
                f"Could not remove stale judge output: {output.path / name}"
            ) from exc
        finally:
            if not succeeded and tombstone_exists:
                try:
                    os.replace(
                        tombstone_name,
                        name,
                        src_dir_fd=output.fd,
                        dst_dir_fd=output.fd,
                    )
                except OSError:
                    pass

    def _tests_dir(self, task_dir: Path) -> Path:
        if task_dir.is_symlink() or not task_dir.is_dir():
            raise SystemExit(f"Task directory must be a regular directory: {task_dir}")
        tests_dir = task_dir / "tests"
        if tests_dir.is_symlink():
            raise SystemExit(f"Task tests directory must not be a symlink: {tests_dir}")
        if not tests_dir.is_dir():
            raise SystemExit(f"Missing tests directory: {tests_dir}")
        try:
            if tests_dir.resolve(strict=True).parent != task_dir.resolve(strict=True):
                raise SystemExit(
                    f"Task tests directory leaves task directory: {tests_dir}"
                )
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid task tests directory: {tests_dir}") from exc
        return tests_dir

    def find_judge(self, task_dir: Path) -> Path:
        tests_dir = self._tests_dir(task_dir)
        names = (
            [self.config.judge_name]
            if self.config.judge_name
            else ["llm_judge.py", "judge.py"]
        )
        for name in names:
            if name is None:
                continue
            _safe_basename(name, "judge_name")
            candidate = tests_dir / name
            if candidate.is_symlink():
                raise SystemExit(f"Judge file must not be a symlink: {candidate}")
            if candidate.is_file():
                return candidate
        raise SystemExit(f"Missing judge file in {tests_dir}")

    def find_rubric(self, task_dir: Path) -> Path:
        tests_dir = self._tests_dir(task_dir)
        rubric_name = self.config.rubric_name or "rubric.txt"
        _safe_basename(rubric_name, "rubric_name")
        rubric_path = tests_dir / rubric_name
        if rubric_path.is_symlink():
            raise SystemExit(f"Rubric file must not be a symlink: {rubric_path}")
        if rubric_path.is_file():
            return rubric_path
        raise SystemExit(f"Missing rubric file: {rubric_path}")

    def resolve_rubric(self, target: JudgeTarget) -> ResolvedRubric:
        self.validate_target_identity(target)
        if self.config.rubric_set is None:
            return self.resolved_local_rubric(self.find_rubric(target.task_dir))

        try:
            bundle = resolve_rubric_bundle(self.config.rubric_set, target.task)
            path = bundle.rendered_path
        except (OSError, UnicodeError, RubricBundleError) as exc:
            raise SystemExit(
                f"Invalid external rubric set for {target.task}: {exc}"
            ) from exc
        return ResolvedRubric(
            text=bundle.rendered_text,
            path=path,
            structured_rubric_sha256=bundle.rubric_sha256,
            rendered_rubric_sha256=self.sha256_text(bundle.rendered_text),
            rubric_id=bundle.rubric_id,
            rubric_set_id=bundle.rubric_set_id,
            source="rubric-set",
            manifest_path=bundle.task_manifest_path,
            manifest_sha256=bundle.task_manifest_sha256,
        )

    def resolved_local_rubric(self, path: Path) -> ResolvedRubric:
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"Rubric path must be a regular file: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"Unreadable rubric file: {path}: {exc}") from exc
        return ResolvedRubric(
            text=text,
            path=path,
            structured_rubric_sha256=None,
            rendered_rubric_sha256=self.sha256_text(text),
            rubric_id=None,
            rubric_set_id=None,
            source="task-local",
            manifest_path=None,
            manifest_sha256=None,
        )

    def rubric_record(self, rubric: ResolvedRubric) -> dict[str, Any]:
        return {
            "rubric": str(rubric.path),
            "structured_rubric_sha256": rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": rubric.rendered_rubric_sha256,
            "rubric_id": rubric.rubric_id,
            "rubric_set_id": rubric.rubric_set_id,
            "rubric_source": rubric.source,
            "rubric_manifest": (
                str(rubric.manifest_path) if rubric.manifest_path is not None else None
            ),
            "manifest_sha256": rubric.manifest_sha256,
        }

    def _stable_artifact_signature(self, value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    def _read_review_artifact(
        self,
        root: Path,
        name: str,
        *,
        root_fd: int | None = None,
    ) -> str:
        _safe_basename(name, "reviewed artifact filename")
        root_path = root.expanduser().absolute()
        artifact_path = root_path / name
        owns_root_fd = root_fd is None
        if root_fd is None:
            root_fd = self._open_directory_fd(root_path, "Reviewed artifact parent")
        else:
            self._validate_directory_fd(
                root_fd,
                root_path,
                "Reviewed artifact parent",
            )
        file_fd: int | None = None
        try:
            try:
                file_fd = os.open(
                    name,
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=root_fd,
                )
                before = os.fstat(file_fd)
                named_before = os.stat(
                    name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SystemExit(
                    f"Reviewed artifact must be a stable regular file: {artifact_path}"
                ) from exc
            if (
                not stat.S_ISREG(before.st_mode)
                or not stat.S_ISREG(named_before.st_mode)
                or (before.st_dev, before.st_ino)
                != (named_before.st_dev, named_before.st_ino)
            ):
                raise SystemExit(
                    f"Reviewed artifact must be a stable regular file: {artifact_path}"
                )

            chunks = []
            try:
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                after = os.fstat(file_fd)
                named_after = os.stat(
                    name,
                    dir_fd=root_fd,
                    follow_symlinks=False,
                )
            except OSError as exc:
                raise SystemExit(
                    f"Reviewed artifact changed while being read: {artifact_path}"
                ) from exc
            if (
                self._stable_artifact_signature(before)
                != self._stable_artifact_signature(after)
                or not stat.S_ISREG(named_after.st_mode)
                or (after.st_dev, after.st_ino)
                != (named_after.st_dev, named_after.st_ino)
            ):
                raise SystemExit(
                    f"Reviewed artifact changed while being read: {artifact_path}"
                )
            self._validate_directory_fd(
                root_fd,
                root_path,
                "Reviewed artifact parent",
            )
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if owns_root_fd:
                os.close(root_fd)
        return self.truncate(b"".join(chunks).decode("utf-8", errors="replace"))

    def _trajectory_review_text(self, raw: str) -> str:
        text = (
            "# Raw Agent Trajectory\n\n"
            "The following JSONL stream is the raw agent trajectory for this task.\n\n"
            "```jsonl\n"
            f"{raw}"
            "\n```\n"
        )
        return self.truncate(text)

    def review_inputs(self, target: JudgeTarget) -> tuple[str, str]:
        identities = self._target_directory_identities(target)
        workspace_path = target.workspace_dir.expanduser().absolute()
        workspace_fd = self._open_directory_fd(
            workspace_path,
            "Reviewed artifact workspace",
        )
        run_fd: int | None = None
        try:
            self._validate_directory_fd(
                workspace_fd,
                workspace_path,
                "Reviewed artifact workspace",
                identities.workspace,
            )
            if self.config.review == "trajectory":
                expected = (target.run_dir / "trajectory.stream.jsonl").absolute()
                if target.trajectory_path.expanduser().absolute() != expected:
                    raise SystemExit(
                        f"trajectory path disagrees with run layout: {target.trajectory_path}"
                    )
                run_path = target.run_dir.expanduser().absolute()
                run_fd = self._open_directory_fd(
                    run_path,
                    "Reviewed artifact run",
                )
                self._validate_directory_fd(
                    run_fd,
                    run_path,
                    "Reviewed artifact run",
                    identities.run,
                )
                raw = self._read_review_artifact(
                    run_path,
                    "trajectory.stream.jsonl",
                    root_fd=run_fd,
                )
                review_text = self._trajectory_review_text(raw)
            elif self.config.review == "trace":
                review_text = self._read_review_artifact(
                    workspace_path,
                    "trace.md",
                    root_fd=workspace_fd,
                )
            else:
                raise SystemExit(f"Unknown review mode: {self.config.review}")

            answer_text = self._read_review_artifact(
                workspace_path,
                "answer.txt",
                root_fd=workspace_fd,
            )
            self._validate_directory_fd(
                workspace_fd,
                workspace_path,
                "Reviewed artifact workspace",
                identities.workspace,
            )
            if run_fd is not None:
                self._validate_directory_fd(
                    run_fd,
                    target.run_dir.expanduser().absolute(),
                    "Reviewed artifact run",
                    identities.run,
                )
            return review_text, answer_text
        finally:
            if run_fd is not None:
                os.close(run_fd)
            os.close(workspace_fd)

    def review_text(self, target: JudgeTarget) -> str:
        if self.config.review == "trace":
            return self._read_review_artifact(target.workspace_dir, "trace.md")
        if self.config.review == "trajectory":
            expected = (target.run_dir / "trajectory.stream.jsonl").absolute()
            if target.trajectory_path.expanduser().absolute() != expected:
                raise SystemExit(
                    f"trajectory path disagrees with run layout: {target.trajectory_path}"
                )
            raw = self._read_review_artifact(
                target.run_dir,
                "trajectory.stream.jsonl",
            )
            return self._trajectory_review_text(raw)
        raise SystemExit(f"Unknown review mode: {self.config.review}")

    def answer_text(self, target: JudgeTarget) -> str:
        return self._read_review_artifact(target.workspace_dir, "answer.txt")

    def execute_judge(
        self,
        judge_path: Path,
        rubric: ResolvedRubric | Path,
        output_dir: Path,
        review_text: str,
        answer_text: str,
        *,
        attempt: JudgeAttempt,
    ) -> dict[str, Any]:
        self.validate_target_identity(attempt.target)
        identities = self._target_directory_identities(attempt.target)
        with self._open_output_directory(
            attempt.target.output_root,
            output_dir,
            expected_root_identity=identities.output_root,
        ) as output:
            return self._execute_judge_with_output(
                judge_path,
                rubric,
                output,
                review_text,
                answer_text,
                attempt=attempt,
            )

    def _execute_judge_with_output(
        self,
        judge_path: Path,
        rubric: ResolvedRubric | Path,
        output: _OpenOutputDirectory,
        review_text: str,
        answer_text: str,
        *,
        attempt: JudgeAttempt,
    ) -> dict[str, Any]:
        self.validate_target_identity(attempt.target)
        self._validate_output_directory(output)
        if isinstance(rubric, Path):
            rubric = self.resolved_local_rubric(rubric)
        if judge_path.is_symlink() or not judge_path.is_file():
            raise SystemExit(f"Judge path must be a regular file: {judge_path}")
        judge_source = judge_path.read_bytes()
        env = os.environ.copy()
        effective_judge_model = self.judge_model(env)
        score_input_attestation = self.score_input_attestation(
            attempt=attempt,
            judge_source=judge_source,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=effective_judge_model,
        )
        output_dir = output.path
        reward_path = output_dir / "reward.json"
        evaluation_path = output_dir / "evaluation.json"
        score_validation_path = output_dir / "score_validation.json"
        stdout_path = output_dir / "stdout.txt"
        for stale_name in (
            "reward.json",
            "evaluation.json",
            "score_validation.json",
            "stdout.txt",
        ):
            self._unlink_output_file(output, stale_name)
        artifact_snapshots: dict[str, bytes] = {}
        with tempfile.TemporaryDirectory(prefix="biomnibench-judge-") as tmp:
            tmp_dir = Path(tmp)
            tests_dir = tmp_dir / "tests"
            logs_dir = tmp_dir / "logs" / "verifier"
            tests_dir.mkdir(parents=True)
            logs_dir.mkdir(parents=True)
            (tests_dir / "rubric.txt").write_bytes(rubric.text.encode("utf-8"))
            (logs_dir / "trace.md").write_text(review_text)
            (logs_dir / "answer.txt").write_text(answer_text)

            rewritten_judge = tmp_dir / judge_path.name
            rewritten_judge.write_text(
                self.rewrite_judge_paths(
                    judge_source.decode("utf-8"),
                    tests_dir,
                    logs_dir,
                )
            )

            env["MODEL_NAME"] = effective_judge_model
            proc = subprocess.run(
                ["uv", "run", str(rewritten_judge)],
                cwd=tmp_dir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self._write_output_text(output, "stdout.txt", proc.stdout)
            for filename in ("reward.json", "evaluation.json"):
                source = logs_dir / filename
                if source.is_file():
                    artifact_snapshots[filename] = source.read_bytes()
                    self._write_output_bytes(
                        output,
                        filename,
                        artifact_snapshots[filename],
                    )

        result = {
            "status": "failed",
            "exit_code": proc.returncode,
            "judge_exit_code": proc.returncode,
            "score": None,
            "reward": str(reward_path),
            "evaluation": str(evaluation_path),
            "stdout": str(stdout_path),
            "score_validation": str(score_validation_path),
        }
        if proc.returncode != 0:
            return result

        try:
            if "reward.json" not in artifact_snapshots:
                raise JudgeScoreValidationError("judge did not produce reward.json")
            if "evaluation.json" not in artifact_snapshots:
                raise JudgeScoreValidationError("judge did not produce evaluation.json")
            validation = self._build_score_validation_from_bytes(
                rubric,
                artifact_snapshots["reward.json"],
                artifact_snapshots["evaluation.json"],
                score_input_attestation,
            )
        except (OSError, UnicodeError, ValueError, JudgeScoreValidationError) as exc:
            return {
                **result,
                "exit_code": 2,
                "validation_error": str(exc),
            }
        self._write_output_text(
            output,
            "score_validation.json",
            json.dumps(validation, indent=2) + "\n",
        )
        return {
            **result,
            "status": "completed",
            "exit_code": 0,
            "score": validation["score"],
        }

    def build_score_validation(
        self,
        rubric: ResolvedRubric,
        reward_path: Path,
        evaluation_path: Path,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        return self._build_score_validation_from_bytes(
            rubric,
            reward_path.read_bytes(),
            evaluation_path.read_bytes(),
            score_input_attestation,
        )

    def _build_score_validation_from_bytes(
        self,
        rubric: ResolvedRubric,
        reward_raw: bytes,
        evaluation_raw: bytes,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            type(score_input_attestation) is not dict
            or set(score_input_attestation) != SCORE_INPUT_ATTESTATION_KEYS
        ):
            raise JudgeScoreValidationError("score input attestation is not exact")
        reward = load_json_strict(reward_raw.decode("utf-8"))
        evaluation = load_json_strict(evaluation_raw.decode("utf-8"))
        reward_sha256 = hashlib.sha256(reward_raw).hexdigest()
        evaluation_sha256 = hashlib.sha256(evaluation_raw).hexdigest()
        validated = validate_judge_score(
            rubric_levels=parse_rubric_levels_strict(rubric.text),
            evaluation=evaluation,
            reward=reward,
        )
        return {
            **score_input_attestation,
            "score": validated.score,
            "raw_score": validated.raw_score,
            "reported_score": validated.reported_score,
            "score_matches_reported": validated.score_matches_reported,
            "selected_levels": validated.selected_levels,
            "criterion_scores": validated.criterion_scores,
            "rubric_source": rubric.source,
            "rubric_set_id": rubric.rubric_set_id,
            "rubric_id": rubric.rubric_id,
            "structured_rubric_sha256": rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": rubric.rendered_rubric_sha256,
            "manifest_sha256": rubric.manifest_sha256,
            "reward_sha256": reward_sha256,
            "evaluation_sha256": evaluation_sha256,
        }

    def valid_score_validation(
        self,
        rubric: ResolvedRubric,
        score_input_attestation: dict[str, Any],
        *,
        output: _OpenOutputDirectory,
    ) -> dict[str, Any] | None:
        try:
            validation = load_json_strict(
                self._read_output_bytes(output, "score_validation.json").decode("utf-8")
            )
            if type(validation) is not dict or set(validation) != SCORE_VALIDATION_KEYS:
                return None
            expected_validation = self._build_score_validation_from_bytes(
                rubric,
                self._read_output_bytes(output, "reward.json"),
                self._read_output_bytes(output, "evaluation.json"),
                score_input_attestation,
            )
            if canonical_json(validation) != canonical_json(expected_validation):
                return None
        except (OSError, UnicodeError, ValueError, JudgeScoreValidationError):
            return None
        return validation

    def score_input_attestation(
        self,
        *,
        attempt: JudgeAttempt,
        judge_source: bytes,
        review_text: str,
        answer_text: str,
        effective_judge_model: str,
    ) -> dict[str, Any]:
        """Attest the exact inputs and implementation used by score computation."""

        self.validate_target_identity(attempt.target)
        identities = self._target_directory_identities(attempt.target)
        if type(attempt.repeat_index) is not int or attempt.repeat_index < 1:
            raise JudgeScoreValidationError("repeat_index must be a positive integer")

        return {
            "schema_version": SCORE_VALIDATION_SCHEMA_VERSION,
            "scorer_version": RUBRIC_SCORER_VERSION,
            "review_input_sha256": self.sha256_text(review_text),
            "answer_input_sha256": self.sha256_text(answer_text),
            "judge_source_sha256": hashlib.sha256(judge_source).hexdigest(),
            "judge_runner_sha256": self.judge_runner_sha256(),
            "scorer_module_sha256": self.scorer_module_sha256(),
            "effective_judge_model": effective_judge_model,
            "review_mode": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "task": attempt.target.task,
            "run_identity": identities.canonical_run,
            "repeat_index": attempt.repeat_index,
        }

    def judge_runner_sha256(self) -> str:
        return self.sha256_file(Path(__file__))

    def scorer_module_sha256(self) -> str:
        return self.sha256_file(Path(__file__).with_name("rubric_scoring.py"))

    def judge_model(self, env: dict[str, str] | None = None) -> str:
        if self.config.model:
            return self.config.model
        if env is not None and env.get("MODEL_NAME"):
            return env["MODEL_NAME"]
        return DEFAULT_JUDGE_MODEL

    def rewrite_judge_paths(self, text: str, tests_dir: Path, logs_dir: Path) -> str:
        tests = tests_dir.as_posix()
        logs = logs_dir.as_posix()
        return (
            text.replace('"/tests/', f'"{tests}/')
            .replace("'/tests/", f"'{tests}/")
            .replace('"/logs/verifier/', f'"{logs}/')
            .replace("'/logs/verifier/", f"'{logs}/")
        )

    def load_json(self, path: Path) -> object:
        return load_json_strict(path.read_text(encoding="utf-8"))

    def sha256_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def sha256_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def read_text(self, path: Path) -> str:
        if not path.is_file():
            return ""
        return self.truncate(path.read_text(errors="replace"))

    def truncate(self, text: str) -> str:
        max_chars = self.config.max_review_chars
        if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
            return text
        head = max_chars // 2
        tail = max_chars - head
        return (
            text[:head]
            + f"\n\n[... truncated by biomnibench judge harness to {max_chars} characters ...]\n\n"
            + text[-tail:]
        )

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


class JudgeProgress(TerminalProgress):
    def __init__(self, *, review: str, total: int) -> None:
        super().__init__(total=total, description=f"judge {review}", unit="task")
        self.review = review

    def record(
        self, _index: int, task: str, event: str, _payload: dict[str, Any]
    ) -> None:
        self.set_status(f"{task}: {event}")
