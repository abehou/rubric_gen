"""Explicit collection scope without deleting or relabelling scientific records."""
from __future__ import annotations

from rubric_gen.submission_revision.experiment import Experiment


def selected_records(experiment: Experiment, study: dict, *, require_terminal: bool = False) -> list[dict]:
    """Validate the full ledger and the declared terminal subset before auditing."""
    records = study.get("records")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise ValueError("study scope requires valid records")
    expected = {a.assignment_id: a for a in experiment.assignments}
    ids = [r.get("assignment_id") for r in records]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError("study scope ledger differs from the full experiment")
    if any(r.get("condition_id") != expected[r["assignment_id"]].condition_id for r in records):
        raise ValueError("study scope condition identity mismatch")
    scope = experiment.execution_conditions
    declared = study.get("execution_conditions")
    if scope is None:
        if declared is not None or (require_terminal and study.get("status") not in {"completed", "failed"}):
            raise ValueError("unscoped audit requires an unscoped terminal study")
        selected = records
    else:
        if declared != list(scope) or (require_terminal and study.get("status") not in {"completed_scope", "failed_scope"}):
            raise ValueError("audit scope differs from the terminal study invocation")
        selected = [r for r in records if r["condition_id"] in scope]
    assignment_scope = study.get("execution_assignment_ids")
    if assignment_scope is not None:
        if (not isinstance(assignment_scope, list) or not assignment_scope
            or len(set(assignment_scope)) != len(assignment_scope)
            or not set(assignment_scope) <= {r["assignment_id"] for r in selected}):
            raise ValueError("invalid study invocation assignment scope")
        selected = [r for r in selected if r["assignment_id"] in assignment_scope]
    if not selected or (require_terminal and any(r.get("status") not in {"completed", "failed", "invalid"} for r in selected)):
        raise ValueError("every selected source assignment must be terminal before audit")
    if study.get("status") in {"completed", "completed_scope"} and any(
        r.get("status") != "completed" for r in selected
    ):
        raise ValueError("completed study scope contains unfinished assignments")
    return selected


def terminal_records(experiment: Experiment, study: dict) -> list[dict]:
    """Use the common full-ledger selection and require terminal audit sources."""
    return selected_records(experiment, study, require_terminal=True)
