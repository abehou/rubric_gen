"""Configuration and immutable value types for BiomniBench judging."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rubric_gen.biomnibench.utils.paths import resolve_project_path


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

_SAFE_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


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
            safe_basename(self.judge_name, "judge_name")
        if self.rubric_name is not None:
            safe_basename(self.rubric_name, "rubric_name")

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
