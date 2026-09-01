"""Execution engine for benchmark submission judges."""

from __future__ import annotations

import hashlib
import os
import stat
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from numbers import Real
from pathlib import Path
from statistics import pstdev
from typing import Any

from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.judging.artifacts import (
    JudgeArtifactStore,
    TargetDirectoryIdentities as _TargetDirectoryIdentities,
)
from rubric_gen.submission_revision.judging.discovery import JudgeTargetDiscovery
from rubric_gen.submission_revision.judging.executor import JudgeExecutor
from rubric_gen.submission_revision.judging.models import (
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
    GradingEngine,
    ResolvedRubric,
    RUBRIC_PATH_SOURCE,
    grading_engine_for_benchmark,
    safe_basename as _safe_basename,
)
from rubric_gen.submission_revision.rubrics.bundles import (
    RubricBundleError,
    resolve_rubric_bundle,
)


_COMPLETED_STATUSES = frozenset({"completed", "skipped"})


@dataclass(frozen=True)
class _TaskScoreSummary:
    record: dict[str, Any]
    score: Real | None
    normalized_score: float | None


def _average(values: tuple[Real, ...], digits: int) -> float | None:
    return round(sum(values) / len(values), digits) if values else None


def _score_stddev(values: tuple[Real, ...]) -> float | None:
    if not values:
        return None
    return round(pstdev(values), 4) if len(values) > 1 else 0.0


def _summarize_task(
    task: str,
    records: list[dict[str, Any]],
) -> _TaskScoreSummary:
    if len(records) != 1:
        raise RuntimeError(f"task {task} must have exactly one judgment")
    result = records[0]
    completed = result.get("status") in _COMPLETED_STATUSES
    score_value = result.get("score")
    score = (
        score_value
        if completed
        and not isinstance(score_value, bool)
        and isinstance(score_value, Real)
        else None
    )
    normalized_value = result.get("normalized_score")
    normalized_score = (
        normalized_value
        if completed and type(normalized_value) is float
        else None
    )
    return _TaskScoreSummary(
        score=score,
        normalized_score=normalized_score,
        record={
            "task": task,
            "status": result.get("status"),
            "score": score,
            "normalized_score": normalized_score,
            "output_dir": result.get("output_dir"),
            "reward": result.get("reward"),
            "evaluation": result.get("evaluation"),
            "stdout": result.get("stdout"),
        },
    )

class SubmissionJudgeRunner:
    def __init__(self, config: JudgeRunConfig) -> None:
        self.config = config
        self.benchmark = get_submission_benchmark(config.benchmark)
        self.artifacts = JudgeArtifactStore(config)
        self.discovery = JudgeTargetDiscovery(config, self.artifacts)
        # The imported implementation is fixed for this Python process. Pin its
        # attestation at construction time as well, so an unrelated source edit
        # during a long-running revision batch cannot invalidate earlier scores
        # or make later scores claim a different implementation identity.
        self._scoring_implementation_sha256 = (
            JudgeExecutor.scoring_implementation_sha256(
            config.benchmark
            )
        )
        self.executor = JudgeExecutor(
            config,
            self.artifacts,
            validate_target=self.validate_target_identity,
            target_identities=self._target_directory_identities,
            resolve_local_rubric=self.resolved_local_rubric,
            scoring_implementation_sha256=(
                self.scoring_implementation_sha256
            ),
        )

    @property
    def scores_path(self) -> Path:
        if self.config.output_path is not None:
            return self.config.output_path
        if self.config.artifacts_dir is not None:
            return self.config.artifacts_dir / f"judge-{self.config.review}-scores.json"
        return self.config.run_dir / f"judge-{self.config.review}-scores.json"

    @property
    def summary_path(self) -> Path:
        return self.scores_path

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
        targets = self.discovery.discover_targets()
        if self.config.artifacts_dir is None:
            return targets
        self.config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        remapped: list[JudgeTarget] = []
        for target in targets:
            digest = hashlib.sha256(
                str(target.run_dir.resolve()).encode("utf-8")
            ).hexdigest()[:8]
            output_root = self.config.artifacts_dir / f"{target.task}--{digest}"
            output_root.mkdir(parents=True, exist_ok=True)
            mapped = replace(target, output_root=output_root)
            self.validate_target_identity(mapped)
            remapped.append(mapped)
        return remapped

    def run(self) -> int:
        targets = self.discover_targets()
        attempts = [JudgeAttempt(target=target) for target in targets]
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
        write_json_atomic(self.scores_path, summary)
        self.print_score_summary(summary)
        print(f"Wrote judge scores: {self.scores_path}")
        return overall_exit

    @property
    def job_count(self) -> int:
        return max(1, self.config.max_concurrency)

    def review_attempt(
        self, attempt: JudgeAttempt, index: int, progress: "JudgeProgress"
    ) -> dict[str, Any]:
        completed = self.completed_record(attempt)
        if completed is not None:
            progress.record(index, attempt.label, "skipped", completed)
            progress.update()
            return completed

        progress.record(index, attempt.label, "started", {})
        record = self.review_target(attempt.target)
        progress.record(index, attempt.label, record.get("status", "completed"), record)
        progress.update()
        return record

    def review_attempt_without_progress(self, attempt: JudgeAttempt) -> dict[str, Any]:
        completed = self.completed_record(attempt)
        if completed is not None:
            return completed
        return self.review_target(attempt.target)

    def score_summary(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            grouped.setdefault(str(record.get("task")), []).append(record)
        task_summaries = tuple(
            _summarize_task(task, task_records)
            for task, task_records in sorted(grouped.items())
        )
        scores = tuple(
            summary.score for summary in task_summaries if summary.score is not None
        )
        normalized_scores = tuple(
            summary.normalized_score
            for summary in task_summaries
            if summary.normalized_score is not None
        )
        tasks = [summary.record for summary in task_summaries]
        return {
            "benchmark": self.config.benchmark.value,
            "grading_engine": grading_engine_for_benchmark(
                self.config.benchmark
            ).value,
            "score_instrument_scope": self.config.benchmark.value,
            "review": self.config.review,
            "max_concurrency": self.job_count,
            "total_tasks": len(tasks),
            "total_attempts": len(records),
            "scored_tasks": len(scores),
            "scored_attempts": len(scores),
            "average_score": _average(scores, 4),
            "average_normalized_score": _average(normalized_scores, 8),
            "score_stddev": _score_stddev(scores),
            "tasks": tasks,
        }

    def print_score_summary(self, summary: dict[str, Any]) -> None:
        print(f"Judge scores ({summary['review']})")
        print("task\tstatus\tscore\tnormalized_score")
        for task in summary["tasks"]:
            score = task["score"] if task["score"] is not None else "-"
            normalized = (
                task["normalized_score"]
                if task["normalized_score"] is not None
                else "-"
            )
            print(f"{task['task']}\t{task['status']}\t{score}\t{normalized}")
        average = summary["average_score"]
        if average is None:
            print(f"Average score: - (0/{summary['total_attempts']} scored attempts)")
        else:
            print(
                f"Average score: {average} "
                f"({summary['scored_attempts']}/{summary['total_attempts']} scored attempts)"
            )
            print(f"Average normalized score: {summary['average_normalized_score']}")

    def completed_record(self, attempt: JudgeAttempt) -> dict[str, Any] | None:
        if not self.config.resume or self.config.force:
            return None
        target = attempt.target
        output_dir = self.output_dir(target)
        reward_path = output_dir / "reward.json"
        evaluation_path = output_dir / "evaluation.json"
        score_validation_path = output_dir / "score_validation.json"
        rubric = self.resolve_rubric(target)
        try:
            review_text, answer_text = self.review_inputs(target)
        except (OSError, UnicodeError):
            return None
        score_input_attestation = self.executor.score_input_attestation(
            attempt=attempt,
            rubric=rubric,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=self.judge_model(os.environ.copy()),
        )
        if not output_dir.exists():
            return None
        identities = self._target_directory_identities(target)
        try:
            with self.artifacts.open_output_directory(
                target.output_root,
                output_dir,
                expected_root_identity=identities.output_root,
                create=False,
            ) as output:
                validation = self.executor.valid_score_validation(
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
            "run_dir": str(target.run_dir),
            "workspace_dir": str(target.workspace_dir),
            "trajectory": str(target.trajectory_path),
            "output_dir": str(output_dir),
            "status": "skipped",
            "exit_code": 0,
            "judge_exit_code": 0,
            "score": validation["score"],
            "normalized_score": validation["normalized_score"],
            "reward": str(reward_path),
            "evaluation": str(evaluation_path),
            "stdout": str(output_dir / "stdout.txt"),
            "score_validation": str(score_validation_path),
            **self.rubric_record(rubric),
        }

    def review_target(self, target: JudgeTarget) -> dict[str, Any]:
        rubric = self.resolve_rubric(target)
        judge_path = self.find_judge(target.task_dir)
        output_dir = self.output_dir(target)

        review_text, answer_text = self.review_inputs(target)

        base_record = {
            "task": target.task,
            "review": self.config.review,
            "run_dir": str(target.run_dir),
            "workspace_dir": str(target.workspace_dir),
            "trajectory": str(target.trajectory_path),
            "judge": str(judge_path),
            "output_dir": str(output_dir),
            **self.rubric_record(rubric),
        }
        identities = self._target_directory_identities(target)
        with self.artifacts.open_output_directory(
            target.output_root,
            output_dir,
            expected_root_identity=identities.output_root,
        ) as output:
            if self.config.save_input_copies:
                self.artifacts.write_output_text(
                    output, "judge_input_trace.md", review_text
                )
                self.artifacts.write_output_text(
                    output, "judge_input_answer.txt", answer_text
                )
            result = self.executor.execute_with_output(
                judge_path,
                rubric,
                output,
                review_text,
                answer_text,
                attempt=JudgeAttempt(target),
            )
        return {**base_record, **result}

    def output_dir(self, target: JudgeTarget) -> Path:
        self.discovery.validated_task_id(target.task)
        return self.artifacts.output_dir(target)

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
        self._tests_dir(task_dir)
        engine = grading_engine_for_benchmark(self.config.benchmark)
        if engine is not GradingEngine.FULL_RUBRIC_STRUCTURED:
            raise SystemExit(f"Unsupported grading engine: {engine.value}")
        judge_name = "full_rubric_judge.py"
        centralized = Path(__file__).with_name(judge_name)
        if centralized.is_symlink() or not centralized.is_file():
            raise SystemExit(
                f"Missing benchmark-fixed {engine.value} judge: {centralized}"
            )
        return centralized

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
        if self.config.rubric_path is not None:
            resolved = self.resolved_local_rubric(self.config.rubric_path)
            return ResolvedRubric(
                text=resolved.text,
                path=resolved.path,
                structured_rubric_sha256=None,
                rendered_rubric_sha256=resolved.rendered_rubric_sha256,
                rubric_id=None,
                rubric_set_id=None,
                source=RUBRIC_PATH_SOURCE,
                manifest_path=None,
                manifest_sha256=None,
            )
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
            rendered_rubric_sha256=hashlib.sha256(bundle.rendered_text.encode("utf-8")).hexdigest(),
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
            rendered_rubric_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
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
            root_fd = self.artifacts.open_directory_fd(root_path, "Reviewed artifact parent")
        else:
            self.artifacts.validate_directory_fd(
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
                self.artifacts.stable_artifact_signature(before)
                != self.artifacts.stable_artifact_signature(after)
                or not stat.S_ISREG(named_after.st_mode)
                or (after.st_dev, after.st_ino)
                != (named_after.st_dev, named_after.st_ino)
            ):
                raise SystemExit(
                    f"Reviewed artifact changed while being read: {artifact_path}"
                )
            self.artifacts.validate_directory_fd(
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
        workspace_fd = self.artifacts.open_directory_fd(
            workspace_path,
            "Reviewed artifact workspace",
        )
        run_fd: int | None = None
        try:
            self.artifacts.validate_directory_fd(
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
                run_fd = self.artifacts.open_directory_fd(
                    run_path,
                    "Reviewed artifact run",
                )
                self.artifacts.validate_directory_fd(
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
            elif self.config.review == "workspace":
                review_text = self._workspace_review_text(
                    target,
                    workspace_fd=workspace_fd,
                )
            else:
                raise SystemExit(f"Unknown review mode: {self.config.review}")

            answer_text = ""
            if self.benchmark.answer_artifact is not None:
                answer_text = self._read_review_artifact(
                    workspace_path,
                    self.benchmark.answer_artifact,
                    root_fd=workspace_fd,
                )
            self.artifacts.validate_directory_fd(
                workspace_fd,
                workspace_path,
                "Reviewed artifact workspace",
                identities.workspace,
            )
            if run_fd is not None:
                self.artifacts.validate_directory_fd(
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
        if self.config.review == "workspace":
            return self._workspace_review_text(target)
        raise SystemExit(f"Unknown review mode: {self.config.review}")

    def _workspace_review_text(
        self,
        target: JudgeTarget,
        *,
        workspace_fd: int | None = None,
    ) -> str:
        """Render the benchmark-native workspace input for judging."""

        try:
            review = self.benchmark.render_workspace_review(
                target.task_dir,
                target.workspace_dir.expanduser().absolute(),
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        return self.truncate(review)

    def answer_text(self, target: JudgeTarget) -> str:
        if self.benchmark.answer_artifact is None:
            return ""
        return self._read_review_artifact(
            target.workspace_dir,
            self.benchmark.answer_artifact,
        )

    def scoring_implementation_sha256(self) -> str:
        return self._scoring_implementation_sha256

    def judge_model(self, env: dict[str, str] | None = None) -> str:
        return self.executor.judge_model(env)

    def truncate(self, text: str) -> str:
        max_chars = self.config.max_review_chars
        if max_chars is None or max_chars <= 0 or len(text) <= max_chars:
            return text
        head = max_chars // 2
        tail = max_chars - head
        return (
            text[:head]
            + f"\n\n[... truncated by submission judge harness to {max_chars} characters ...]\n\n"
            + text[-tail:]
        )



class JudgeProgress(TerminalProgress):
    def __init__(self, *, review: str, total: int) -> None:
        super().__init__(total=total, description=f"judge {review}", unit="task")
        self.review = review

    def record(
        self, _index: int, task: str, event: str, _payload: dict[str, Any]
    ) -> None:
        self.set_status(f"{task}: {event}")
