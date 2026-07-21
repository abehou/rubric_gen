"""Publish lightweight revision summaries inside the repository."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

from rubric_gen.biomnibench.revision.artifacts import (
    read_json_object,
    sha256_file,
    write_json_atomic,
)
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT


REPORTS_ROOT_ENV = "BIOMNIBENCH_REPORTS_ROOT"


def revision_reports_root() -> Path:
    configured = os.environ.get(REPORTS_ROOT_ENV)
    root = (
        Path(configured).expanduser()
        if configured
        else PROJECT_ROOT / "runs" / "biomnibench-reports"
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

    report_dir = revision_reports_root() / experiment_dir.name
    report_dir.mkdir(parents=True, exist_ok=True)
    destination_plot = report_dir / "score_improvement.png"
    temporary_plot = report_dir / f".score-improvement-{secrets.token_hex(8)}.tmp"
    try:
        shutil.copyfile(plot, temporary_plot, follow_symlinks=False)
        os.replace(temporary_plot, destination_plot)
    finally:
        if os.path.lexists(temporary_plot):
            temporary_plot.unlink()

    scores = state.get("scores")
    revision_rounds = manifest.get("revision_rounds")
    if (
        type(scores) is not list
        or any(type(score) is not int for score in scores)
        or type(revision_rounds) is not int
    ):
        raise RuntimeError("revision report source has invalid score state")
    summary = {
        "schema_version": 1,
        "experiment_dir": str(experiment_dir),
        "task_id": manifest.get("task_id"),
        "phase": state.get("phase"),
        "completed_rounds": len(scores),
        "total_rounds": revision_rounds + 1,
        "scores": scores,
        "feedback_policy": manifest.get("feedback_policy"),
        "mitigation": manifest.get("mitigation", "none"),
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
