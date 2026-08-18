"""Publish lightweight revision summaries inside the repository."""

from __future__ import annotations

import os
import math
import secrets
import shutil
from numbers import Real
from pathlib import Path

from rubric_gen.submission_revision.artifacts import (
    read_json_object,
    sha256_file,
)
from rubric_gen.runtime.paths import PROJECT_ROOT
from rubric_gen.artifacts.serialization import write_json_atomic


REPORTS_ROOT_ENV = "BIOMNIBENCH_REPORTS_ROOT"


def _report_relative_directory(experiment_dir: Path, task_id: str) -> Path:
    for parent in experiment_dir.parents:
        if (parent / "batch.json").is_file():
            relative = experiment_dir.relative_to(parent)
            return Path(parent.name, *relative.parts)
    return Path(experiment_dir.name, task_id)


def revision_reports_root() -> Path:
    configured = os.environ.get(REPORTS_ROOT_ENV)
    root = (
        Path(configured).expanduser()
        if configured
        else PROJECT_ROOT / "runs" / "submission-reports"
    )
    if not root.is_absolute():
        raise RuntimeError(f"{REPORTS_ROOT_ENV} must be an absolute path")
    return root


def publish_revision_report(experiment_dir: Path) -> Path:
    """Copy only the plot and a compact state summary into the Git worktree."""
    experiment_dir = Path(experiment_dir).resolve()
    manifest = read_json_object(experiment_dir / "manifest.json", "revision manifest")
    state = read_json_object(experiment_dir / "state.json", "revision state")
    plot = experiment_dir / "score_improvement.png"
    if plot.is_symlink() or not plot.is_file():
        raise RuntimeError(f"revision score plot does not exist: {plot}")

    task_id = manifest.get("task_id")
    if type(task_id) is not str or not task_id:
        raise RuntimeError("revision report manifest has no task ID")
    report_dir = revision_reports_root() / _report_relative_directory(
        experiment_dir, task_id
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    destination_plot = report_dir / "score_improvement.png"
    temporary_plot = report_dir / f".score-improvement-{secrets.token_hex(8)}.tmp"
    try:
        shutil.copyfile(plot, temporary_plot, follow_symlinks=False)
        os.replace(temporary_plot, destination_plot)
    finally:
        if os.path.lexists(temporary_plot):
            temporary_plot.unlink()

    on_policy_scores = state.get("scores")
    fixed_original_scores = state.get("fixed_original_scores")
    revision_rounds = manifest.get("revision_rounds")
    if (
        type(on_policy_scores) is not list
        or any(
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
            for score in on_policy_scores
        )
        or type(fixed_original_scores) is not list
        or any(
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
            for score in fixed_original_scores
        )
        or len(fixed_original_scores) != len(on_policy_scores)
        or type(revision_rounds) is not int
    ):
        raise RuntimeError("revision report source has invalid score state")
    summary = {
        "experiment_dir": str(experiment_dir),
        "task_id": manifest.get("task_id"),
        "phase": state.get("phase"),
        "completed_rounds": len(on_policy_scores),
        "total_rounds": revision_rounds + 1,
        "on_policy_scores": on_policy_scores,
        "fixed_original_scores": fixed_original_scores,
        "feedback_policy": manifest.get("feedback_policy"),
        "prompt": manifest["prompt"],
        "rubric_policy": manifest["rubric_policy"],
        "provider": manifest.get("provider"),
        "solver_model": manifest.get("model"),
        "judge_model": manifest.get("judge_model"),
        "review": manifest.get("review"),
        "rubric_name": manifest.get("rubric_name"),
        "rubric_set": manifest.get("rubric_set"),
        "score_plot_sha256": sha256_file(destination_plot),
    }
    write_json_atomic(report_dir / "summary.json", summary)
    return report_dir
