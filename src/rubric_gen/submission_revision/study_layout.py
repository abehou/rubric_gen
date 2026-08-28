"""Own safe randomized-study experiment paths."""

from __future__ import annotations

from pathlib import Path


def study_experiment_relative_path(assignment: dict[str, object]) -> Path:
    task_id = assignment.get("task_id")
    replicate = assignment.get("replicate")
    condition_id = assignment.get("condition_id")
    if (
        type(task_id) is not str
        or not task_id
        or Path(task_id).name != task_id
        or type(replicate) is not int
        or replicate < 1
        or type(condition_id) is not str
        or not condition_id
        or Path(condition_id).name != condition_id
    ):
        raise RuntimeError("assignment has an unsafe experiment identity")
    return Path("experiments") / task_id / f"rep-{replicate:03d}" / condition_id


def resolve_study_experiment(
    study_root: Path,
    record: dict[str, object],
    assignment: dict[str, object],
) -> Path:
    expected_relative = study_experiment_relative_path(assignment)
    expected_identity = {
        "assignment_id": assignment.get("assignment_id"),
        "task_id": assignment.get("task_id"),
        "replicate": assignment.get("replicate"),
        "condition_id": assignment.get("condition_id"),
        "execution_order": assignment.get("execution_order"),
        "experiment_dir": expected_relative.as_posix(),
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("study record identity differs from its assignment")
    current = study_root
    for component in expected_relative.parts:
        current = current / component
        if current.is_symlink():
            raise RuntimeError(f"study experiment path contains a symlink: {current}")
    return study_root / expected_relative
