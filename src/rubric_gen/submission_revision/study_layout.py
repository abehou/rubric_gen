"""Own safe randomized-study experiment paths."""

from __future__ import annotations

from pathlib import Path

from rubric_gen.submission_revision.assignments import ExperimentAssignment


def study_experiment_relative_path(assignment: ExperimentAssignment) -> Path:
    return assignment.study_relative_path


def resolve_study_experiment(
    study_root: Path,
    record: dict[str, object],
    assignment: ExperimentAssignment,
) -> Path:
    expected_relative = study_experiment_relative_path(assignment)
    expected_identity = assignment.record_identity()
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("study record identity differs from its assignment")
    current = study_root
    for component in expected_relative.parts:
        current = current / component
        if current.is_symlink():
            raise RuntimeError(f"study experiment path contains a symlink: {current}")
    return study_root / expected_relative
