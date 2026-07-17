"""Execution engine for BiomniBench task judges."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from statistics import pstdev
from typing import Any, Iterator

from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.judging.artifacts import (
    JudgeArtifactStore,
    OpenOutputDirectory as _OpenOutputDirectory,
    TargetDirectoryIdentities as _TargetDirectoryIdentities,
)
from rubric_gen.biomnibench.judging.discovery import JudgeTargetDiscovery
from rubric_gen.biomnibench.judging.executor import JudgeExecutor
from rubric_gen.biomnibench.judging.models import (
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
    ResolvedRubric,
    safe_basename as _safe_basename,
)
from rubric_gen.biomnibench.rubrics.bundles import (
    RubricBundleError,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.rubrics.schema import load_json_strict

class BiomniBenchJudgeRunner:
    def __init__(self, config: JudgeRunConfig) -> None:
        self.config = config
        self.artifacts = JudgeArtifactStore(config)
        self.discovery = JudgeTargetDiscovery(config, self.artifacts)
        self.executor = JudgeExecutor(
            config,
            self.artifacts,
            validate_target=lambda target: self.validate_target_identity(target),
            target_identities=lambda target: self._target_directory_identities(target),
            resolve_local_rubric=lambda path: self.resolved_local_rubric(path),
            judge_runner_sha256=lambda: self.judge_runner_sha256(),
            scorer_module_sha256=lambda: self.scorer_module_sha256(),
        )

    @property
    def scores_path(self) -> Path:
        if self.config.output_path is not None:
            return self.config.output_path
        return self.config.run_dir / f"judge-{self.config.review}-scores.json"

    @property
    def summary_path(self) -> Path:
        return self.scores_path

    def _validated_task_id(self, task: object) -> str:
        return self.discovery.validated_task_id(task)

    def _canonical_task_dir(
        self, task: object, status_task_dir: object | None = None
    ) -> Path:
        return self.discovery.canonical_task_dir(task, status_task_dir)

    def _validated_workspace(
        self, workspace: Path, *, expected: Path | tuple[Path, ...]
    ) -> Path:
        return self.discovery.validated_workspace(workspace, expected=expected)

    def _standalone_workspace_options(self, run_dir: Path) -> tuple[Path, ...]:
        return self.discovery.standalone_workspace_options(run_dir)

    def validate_target_identity(self, target: JudgeTarget) -> None:
        self.discovery.validate_target_identity(target)

    def _target_directory_identities(
        self, target: JudgeTarget
    ) -> _TargetDirectoryIdentities:
        identities = self.artifacts.target_identities(target)
        if identities is None:
            self.validate_target_identity(target)
            identities = self.artifacts.target_identities(target)
        assert identities is not None
        return identities

    def discover_targets(self) -> list[JudgeTarget]:
        return self.discovery.discover_targets()

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
            target.output_root, base / f"repeat-{repeat_index:02d}"
        )

    def _safe_output_path(self, output_root: Path, candidate: Path) -> Path:
        return self.artifacts.safe_output_path(output_root, candidate)

    def _directory_open_flags(self) -> int:
        return self.artifacts.directory_open_flags()

    def _directory_fd_identity(self, fd: int) -> tuple[int, int]:
        return self.artifacts.directory_fd_identity(fd)

    def _validate_directory_fd(
        self,
        fd: int,
        path: Path,
        context: str,
        expected_identity: tuple[int, int] | None = None,
    ) -> None:
        self.artifacts.validate_directory_fd(
            fd, path, context, expected_identity
        )

    def _open_directory_fd(self, path: Path, context: str) -> int:
        return self.artifacts.open_directory_fd(path, context)

    @contextmanager
    def _open_output_directory(
        self,
        output_root: Path,
        output_dir: Path,
        *,
        expected_root_identity: tuple[int, int],
        create: bool = True,
    ) -> Iterator[_OpenOutputDirectory]:
        self._safe_output_path(output_root, output_dir)
        with self.artifacts.open_output_directory(
            output_root,
            output_dir,
            expected_root_identity=expected_root_identity,
            create=create,
        ) as output:
            self._safe_output_path(output_root, output_dir)
            yield output

    def _validate_output_directory(self, output: _OpenOutputDirectory) -> None:
        self.artifacts.validate_output_directory(output)

    def _read_output_bytes(
        self, output: _OpenOutputDirectory, name: str
    ) -> bytes:
        return self.artifacts.read_output_bytes(output, name)

    def _write_output_text(
        self, output: _OpenOutputDirectory, name: str, text: str
    ) -> None:
        self.artifacts.write_output_text(output, name, text)

    def _write_output_bytes(
        self, output: _OpenOutputDirectory, name: str, payload: bytes
    ) -> None:
        self.artifacts.write_output_bytes(output, name, payload)

    def _unlink_output_file(
        self, output: _OpenOutputDirectory, name: str
    ) -> None:
        self.artifacts.unlink_output_file(output, name)

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
        return self.executor.execute_with_output(
            judge_path,
            rubric,
            output,
            review_text,
            answer_text,
            attempt=attempt,
        )

    def build_score_validation(
        self,
        rubric: ResolvedRubric,
        reward_path: Path,
        evaluation_path: Path,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        return self.executor.build_score_validation(
            rubric, reward_path, evaluation_path, score_input_attestation
        )

    def _build_score_validation_from_bytes(
        self,
        rubric: ResolvedRubric,
        reward_raw: bytes,
        evaluation_raw: bytes,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        return self.executor.build_score_validation_from_bytes(
            rubric, reward_raw, evaluation_raw, score_input_attestation
        )

    def valid_score_validation(
        self,
        rubric: ResolvedRubric,
        score_input_attestation: dict[str, Any],
        *,
        output: _OpenOutputDirectory,
    ) -> dict[str, Any] | None:
        return self.executor.valid_score_validation(
            rubric, score_input_attestation, output=output
        )

    def score_input_attestation(
        self,
        *,
        attempt: JudgeAttempt,
        judge_source: bytes,
        review_text: str,
        answer_text: str,
        effective_judge_model: str,
    ) -> dict[str, Any]:
        return self.executor.score_input_attestation(
            attempt=attempt,
            judge_source=judge_source,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=effective_judge_model,
        )

    def judge_runner_sha256(self) -> str:
        return self.executor.judge_runner_sha256()

    def scorer_module_sha256(self) -> str:
        return self.executor.scorer_module_sha256()

    def judge_model(self, env: dict[str, str] | None = None) -> str:
        return self.executor.judge_model(env)

    def rewrite_judge_paths(
        self, text: str, tests_dir: Path, logs_dir: Path
    ) -> str:
        return self.executor.rewrite_judge_paths(text, tests_dir, logs_dir)

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
