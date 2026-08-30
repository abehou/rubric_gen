"""Validate a completed randomized submission-revision experiment."""

from __future__ import annotations

from pathlib import Path

from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.study_validation_artifacts import (
    validate_revision_artifacts,
)
from rubric_gen.submission_revision.study_validation_context import (
    build_validation_context,
    validate_manifest,
    validate_state,
)


def validate_completed_revision(
    experiment_dir: Path,
    assignment: dict[str, object],
    experiment: Experiment,
    seed_run_dir: Path,
    paraphrase_run_dir: Path,
) -> None:
    context = build_validation_context(
        experiment_dir,
        assignment,
        experiment,
        seed_run_dir,
        paraphrase_run_dir,
    )
    validate_manifest(context)
    validate_state(context)
    validate_revision_artifacts(context)
