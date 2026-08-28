"""Configuration and immutable value types for benchmark judging."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.runtime.paths import PROJECT_ROOT, resolve_project_path


DEFAULT_JUDGE_MODEL = "gpt-5.6-luna"
JUDGMENT_REPEATS = 5
RUBRIC_PATH_SOURCE = "rubric-path"
SCORE_INPUT_ATTESTATION_KEYS = {
    "review_input_sha256",
    "answer_input_sha256",
    "scoring_implementation_sha256",
    "effective_judge_model",
    "judge_api_base",
    "benchmark",
    "grading_engine",
    "engine_execution",
    "review_mode",
    "max_review_chars",
    "task",
    "run_identity",
    "repeat_index",
}
SCORE_VALIDATION_KEYS = {
    "score",
    "normalized_score",
    "raw_score",
    "reported_score",
    "score_matches_reported",
    "criterion_level_votes",
    "criterion_scores",
    "rubric_source",
    "rubric_set_id",
    "rubric_id",
    "structured_rubric_sha256",
    "rendered_rubric_sha256",
    "manifest_sha256",
    "reward_sha256",
    "evaluation_sha256",
    "usage_sha256",
    "engine_metrics",
} | SCORE_INPUT_ATTESTATION_KEYS

_SAFE_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class GradingEngine(str, Enum):
    """The one scoring instrument used by all submission benchmarks."""

    FULL_RUBRIC_STRUCTURED = "full-rubric-structured"


def grading_engine_for_benchmark(
    benchmark: SubmissionBenchmarkId | str,
) -> GradingEngine:
    """Return the fixed engine. No selector or runtime fallback exists."""

    resolved = SubmissionBenchmarkId(benchmark)
    if resolved in {
        SubmissionBenchmarkId.BIOMNIBENCH_DA,
        SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
    }:
        return GradingEngine.FULL_RUBRIC_STRUCTURED
    raise ValueError(f"no grading engine is registered for {resolved.value}")


def safe_basename(value: object, context: str) -> str:
    """Validate one filesystem component accepted from a CLI/configuration."""
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
    benchmark: SubmissionBenchmarkId = SubmissionBenchmarkId.BIOMNIBENCH_DA
    extra_run_dirs: tuple[Path, ...] = ()
    review: str = "trace"
    model: str | None = None
    base_url: str | None = None
    output_path: Path | None = None
    rubric_name: str | None = None
    rubric_set: Path | None = None
    rubric_path: Path | None = None
    limit: int | None = None
    max_review_chars: int | None = None
    resume: bool = False
    force: bool = False
    max_concurrency: int = 1
    repeats: int = 1
    save_input_copies: bool = True
    artifacts_dir: Path | None = None

    def __post_init__(self) -> None:
        get_submission_benchmark(self.benchmark).validate_review(self.review)
        if sum(value is not None for value in (
            self.rubric_name, self.rubric_set, self.rubric_path
        )) > 1:
            raise ValueError("rubric_name, rubric_set, and rubric_path are mutually exclusive")
        if self.rubric_name is not None:
            safe_basename(self.rubric_name, "rubric_name")

    @classmethod
    def from_namespace(cls, args: Any) -> "JudgeRunConfig":
        output = getattr(args, "output", None)
        artifacts_dir = getattr(args, "output_dir", None)
        run_dir_args = getattr(args, "run_dir")
        raw_run_dirs = []
        for item in run_dir_args if isinstance(run_dir_args, list) else [run_dir_args]:
            if isinstance(item, list):
                raw_run_dirs.extend(item)
            else:
                raw_run_dirs.append(item)
        run_dirs = tuple(resolve_project_path(run_dir) for run_dir in raw_run_dirs)
        if artifacts_dir:
            resolved_artifacts_dir = resolve_project_path(artifacts_dir)
        else:
            identity = hashlib.sha256(
                "\0".join(str(path) for path in run_dirs).encode("utf-8")
            ).hexdigest()[:8]
            resolved_artifacts_dir = (
                PROJECT_ROOT
                / "runs"
                / "submission-judges"
                / f"{run_dirs[0].name}--{identity}"
            )
        return cls(
            run_dir=run_dirs[0],
            tasks_dir=resolve_project_path(getattr(args, "tasks_dir")),
            benchmark=SubmissionBenchmarkId(
                getattr(args, "benchmark", SubmissionBenchmarkId.BIOMNIBENCH_DA)
            ),
            extra_run_dirs=run_dirs[1:],
            review=getattr(args, "review", "trace"),
            model=getattr(args, "model", None),
            output_path=resolve_project_path(output) if output else None,
            rubric_name=getattr(args, "rubric", None),
            rubric_set=(
                resolve_project_path(getattr(args, "rubric_set"))
                if getattr(args, "rubric_set", None)
                else None
            ),
            limit=getattr(args, "limit", None),
            max_review_chars=getattr(args, "max_review_chars", None),
            resume=getattr(args, "resume", False),
            force=getattr(args, "force", False),
            max_concurrency=max(1, getattr(args, "max_concurrency", 1)),
            repeats=max(1, getattr(args, "repeats", 1)),
            artifacts_dir=resolved_artifacts_dir,
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
