"""Run BiomniBench task judges over saved agent runs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import pstdev
from typing import Any

from rubric_gen.biomnibench.common import PROGRESS_BAR_FORMAT, resolve_project_path
from rubric_gen.biomnibench.rubric_scoring import (
    JudgeScoreValidationError,
    RUBRIC_SCORER_VERSION,
    parse_rubric_levels_strict,
    validate_judge_score,
)
from rubric_gen.biomnibench.task_rubric_compiler import (
    RubricBundleError,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.task_rubrics import canonical_json, load_json_strict

try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - tqdm is an optional runtime nicety.
    tqdm = None


DEFAULT_JUDGE_MODEL = "gemini-3.1-pro"
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


class BiomniBenchJudgeRunner:
    def __init__(self, config: JudgeRunConfig) -> None:
        self.config = config

    @property
    def scores_path(self) -> Path:
        if self.config.output_path is not None:
            return self.config.output_path
        return self.config.run_dir / f"judge-{self.config.review}-scores.json"

    @property
    def summary_path(self) -> Path:
        return self.scores_path

    def discover_targets(self) -> list[JudgeTarget]:
        targets = []
        for run_dir in self.config.run_dirs:
            if (run_dir / "tasks").is_dir() and (run_dir / "workspaces").is_dir():
                targets.extend(self._discover_batch_targets(run_dir))
            else:
                targets.append(self._discover_single_target(run_dir))
        if self.config.limit is not None:
            return targets[: self.config.limit]
        return targets

    def _discover_batch_targets(self, batch_dir: Path) -> list[JudgeTarget]:
        targets = []
        for task_run_dir in sorted((batch_dir / "tasks").iterdir()):
            if not task_run_dir.is_dir():
                continue
            task = task_run_dir.name
            status = self._read_json(task_run_dir / "status.json")
            task_dir = Path(status.get("task_dir") or self.config.tasks_dir / task)
            targets.append(
                JudgeTarget(
                    task=task,
                    task_dir=task_dir,
                    run_dir=task_run_dir,
                    workspace_dir=Path(status.get("workspace_dir") or batch_dir / "workspaces" / task),
                    trajectory_path=task_run_dir / "trajectory.stream.jsonl",
                    output_root=batch_dir,
                )
            )
        return targets

    def _discover_single_target(self, run_dir: Path) -> JudgeTarget:
        status = self._read_json(run_dir / "status.json")
        task = status.get("task") or self._infer_task_name(run_dir)
        task_dir = Path(status.get("task_dir") or self.config.tasks_dir / task)
        workspace = status.get("workspace_dir")
        if workspace is None and run_dir.parent.name == "tasks":
            workspace = run_dir.parents[1] / "workspaces" / task
        if workspace is None:
            workspace = run_dir / "workspace"
        return JudgeTarget(
            task=task,
            task_dir=task_dir,
            run_dir=run_dir,
            workspace_dir=Path(workspace),
            trajectory_path=run_dir / "trajectory.stream.jsonl",
            output_root=run_dir,
        )

    def _infer_task_name(self, run_dir: Path) -> str:
        parts = run_dir.name.split("-")
        for index in range(len(parts) - 2):
            if parts[index].startswith("da") and parts[index + 1].isdigit() and parts[index + 2].isdigit():
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
                        executor.submit(self.review_attempt_without_progress, attempt): attempt
                        for attempt in attempts
                    }
                    for index, future in enumerate(as_completed(futures), start=1):
                        attempt = futures[future]
                        record = future.result()
                        records.append(record)
                        progress.record(index, attempt.label, record.get("status", "completed"), record)
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

    def review_attempt(self, attempt: JudgeAttempt, index: int, progress: "JudgeProgress") -> dict[str, Any]:
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
            task_records = sorted(task_records, key=lambda item: int(item.get("repeat_index") or 1))
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
                    "score": task_scores[0] if len(task_records) == 1 and task_scores else None,
                    "scores": task_scores,
                    "mean_score": round(sum(task_scores) / len(task_scores), 4) if task_scores else None,
                    "score_stddev": round(pstdev(task_scores), 4) if len(task_scores) > 1 else 0.0 if task_scores else None,
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
            "score_stddev": round(pstdev(scores), 4) if len(scores) > 1 else 0.0 if scores else None,
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
            scores = ",".join(str(score) for score in task["scores"]) if task["scores"] else "-"
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
            review_text = self.review_text(target)
            answer_text = self.read_text(target.workspace_dir / "answer.txt")
            judge_source = judge_path.read_bytes()
        except (OSError, UnicodeError):
            return None
        score_input_attestation = self.score_input_attestation(
            judge_source=judge_source,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=self.judge_model(os.environ.copy()),
        )
        validation = self.valid_score_validation(
            rubric,
            reward_path,
            evaluation_path,
            score_validation_path,
            score_input_attestation,
        )
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

    def review_target(self, target: JudgeTarget, repeat_index: int = 1) -> dict[str, Any]:
        rubric = self.resolve_rubric(target)
        judge_path = self.find_judge(target.task_dir)
        output_dir = self.output_dir(target, repeat_index)
        output_dir.mkdir(parents=True, exist_ok=True)

        review_text = self.review_text(target)
        answer_text = self.read_text(target.workspace_dir / "answer.txt")
        (output_dir / "judge_input_trace.md").write_text(review_text)
        (output_dir / "judge_input_answer.txt").write_text(answer_text)

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

        result = self.execute_judge(judge_path, rubric, output_dir, review_text, answer_text)
        return {**base_record, **result}

    def output_dir(self, target: JudgeTarget, repeat_index: int = 1) -> Path:
        base = target.output_root / "judges" / self.config.review / target.task
        if self.repeat_count == 1:
            return base
        return base / f"repeat-{repeat_index:02d}"

    def find_judge(self, task_dir: Path) -> Path:
        tests_dir = task_dir / "tests"
        names = [self.config.judge_name] if self.config.judge_name else ["llm_judge.py", "judge.py"]
        for name in names:
            if name is None:
                continue
            candidate = tests_dir / name
            if candidate.is_file():
                return candidate
        raise SystemExit(f"Missing judge file in {tests_dir}")

    def find_rubric(self, task_dir: Path) -> Path:
        rubric_path = task_dir / "tests" / (self.config.rubric_name or "rubric.txt")
        if rubric_path.is_file():
            return rubric_path
        raise SystemExit(f"Missing rubric file: {rubric_path}")

    def resolve_rubric(self, target: JudgeTarget) -> ResolvedRubric:
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

    def review_text(self, target: JudgeTarget) -> str:
        if self.config.review == "trace":
            return self.read_text(target.workspace_dir / "trace.md")
        if self.config.review == "trajectory":
            raw = self.read_text(target.trajectory_path)
            text = (
                "# Raw Agent Trajectory\n\n"
                "The following JSONL stream is the raw agent trajectory for this task.\n\n"
                "```jsonl\n"
                f"{raw}"
                "\n```\n"
            )
            return self.truncate(text)
        raise SystemExit(f"Unknown review mode: {self.config.review}")

    def execute_judge(
        self,
        judge_path: Path,
        rubric: ResolvedRubric | Path,
        output_dir: Path,
        review_text: str,
        answer_text: str,
    ) -> dict[str, Any]:
        if isinstance(rubric, Path):
            rubric = self.resolved_local_rubric(rubric)
        judge_source = judge_path.read_bytes()
        env = os.environ.copy()
        effective_judge_model = self.judge_model(env)
        score_input_attestation = self.score_input_attestation(
            judge_source=judge_source,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=effective_judge_model,
        )
        reward_path = output_dir / "reward.json"
        evaluation_path = output_dir / "evaluation.json"
        score_validation_path = output_dir / "score_validation.json"
        stdout_path = output_dir / "stdout.txt"
        for stale in (reward_path, evaluation_path, score_validation_path, stdout_path):
            stale.unlink(missing_ok=True)
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
            rewritten_judge.write_text(self.rewrite_judge_paths(
                judge_source.decode("utf-8"),
                tests_dir,
                logs_dir,
            ))

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
            stdout_path.write_text(proc.stdout)
            for filename in ("reward.json", "evaluation.json"):
                source = logs_dir / filename
                if source.is_file():
                    shutil.copy2(source, output_dir / filename)

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
            validation = self.build_score_validation(
                rubric,
                reward_path,
                evaluation_path,
                score_input_attestation,
            )
        except (OSError, UnicodeError, ValueError, JudgeScoreValidationError) as exc:
            return {
                **result,
                "exit_code": 2,
                "validation_error": str(exc),
            }
        score_validation_path.write_text(json.dumps(validation, indent=2) + "\n")
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
        if (
            type(score_input_attestation) is not dict
            or set(score_input_attestation) != SCORE_INPUT_ATTESTATION_KEYS
        ):
            raise JudgeScoreValidationError("score input attestation is not exact")
        reward, reward_sha256 = self.load_json_snapshot(reward_path)
        evaluation, evaluation_sha256 = self.load_json_snapshot(evaluation_path)
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
        reward_path: Path,
        evaluation_path: Path,
        score_validation_path: Path,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            validation = self.load_json(score_validation_path)
            if type(validation) is not dict or set(validation) != SCORE_VALIDATION_KEYS:
                return None
            expected_validation = self.build_score_validation(
                rubric,
                reward_path,
                evaluation_path,
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
        judge_source: bytes,
        review_text: str,
        answer_text: str,
        effective_judge_model: str,
    ) -> dict[str, Any]:
        """Attest the exact inputs and implementation used by score computation."""

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

    def load_json_snapshot(self, path: Path) -> tuple[object, str]:
        raw = path.read_bytes()
        value = load_json_strict(raw.decode("utf-8"))
        return value, hashlib.sha256(raw).hexdigest()

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


class JudgeProgress:
    def __init__(self, *, review: str, total: int) -> None:
        self.review = review
        self.total = total
        self._bar: Any = None

    def __enter__(self) -> "JudgeProgress":
        if tqdm is not None:
            self._bar = tqdm(
                total=self.total,
                desc=f"judge {self.review}",
                unit="task",
                dynamic_ncols=True,
                bar_format=PROGRESS_BAR_FORMAT,
                file=sys.stderr,
            )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._bar is not None:
            self._bar.close()

    def record(self, _index: int, task: str, event: str, _payload: dict[str, Any]) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(f"{task}: {event}")

    def update(self) -> None:
        if self._bar is not None:
            self._bar.update(1)
