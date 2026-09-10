from copy import deepcopy
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.study import StudyRunner


def fixture():
    assignments = tuple(SimpleNamespace(assignment_id=str(i), condition_id=c)
                        for i, c in enumerate(("full-static", "full-static", "semi-static")))
    experiment = SimpleNamespace(assignments=assignments, execution_conditions=("full-static",))
    ledger = {"status": "completed_scope", "execution_conditions": ["full-static"],
              "records": [{"assignment_id": a.assignment_id, "condition_id": a.condition_id,
                           "status": "completed" if i < 2 else "pending"}
                          for i, a in enumerate(assignments)]}
    return experiment, ledger


def test_scope_allows_excluded_pending_without_mutation():
    experiment, ledger = fixture()
    before = deepcopy(ledger)
    assert len(terminal_records(experiment, ledger)) == 2
    assert ledger == before
    ledger["records"][2]["status"] = "failed"
    assert len(terminal_records(experiment, ledger)) == 2


@pytest.mark.parametrize("mutation", [
    lambda l: l.update(status="completed"),
    lambda l: l.update(execution_conditions=["semi-static"]),
    lambda l: l["records"].pop(),
    lambda l: l["records"].append(l["records"][0]),
    lambda l: l["records"][0].update(condition_id="semi-static"),
    lambda l: l["records"][0].update(status="pending"),
])
def test_scope_rejects_inconsistent_evidence(mutation):
    experiment, ledger = fixture()
    mutation(ledger)
    with pytest.raises(ValueError):
        terminal_records(experiment, ledger)


def test_dispatch_and_completion_preserve_full_ledger():
    experiment, ledger = fixture()
    runner = object.__new__(StudyRunner)
    runner.experiment = experiment
    runner.config = SimpleNamespace(assignment_ids=None)
    runner._write_manifest = lambda value: None
    ledger["records"][1]["status"] = "running"
    ledger["records"][2]["status"] = "failed"
    assert [a.assignment_id for a in runner._pending_assignments(ledger, experiment.assignments)] == ["1"]
    ledger["records"][1]["status"] = "completed"
    assert runner._finish_study(ledger) == 0
    assert ledger["status"] == "completed_scope"
    assert len(ledger["records"]) == 3
    assert ledger["records"][2]["status"] == "failed"


def test_counted_smoke_scope_keeps_scientific_ledger_and_identity():
    experiment, ledger = fixture()
    runner = object.__new__(StudyRunner)
    runner.experiment = experiment
    runner.config = SimpleNamespace(assignment_ids=("1",),max_concurrency=32)
    runner._write_manifest = lambda value: None
    ledger["records"][0]["status"] = "pending"
    ledger["records"][1]["status"] = "pending"
    assert [a.assignment_id for a in runner._pending_assignments(ledger,experiment.assignments)] == ["1"]
    runner._mark_study_running(ledger)
    ledger["records"][1]["status"] = "completed"
    assert runner._finish_study(ledger) == 0
    assert len(ledger["records"]) == 3
    assert ledger["execution_assignment_ids"] == ["1"]
    assert [r["assignment_id"] for r in terminal_records(experiment,ledger)] == ["1"]
    runner.config = SimpleNamespace(assignment_ids=None,max_concurrency=32)
    runner._mark_study_running(ledger)
    assert "execution_assignment_ids" not in ledger
    assert [a.assignment_id for a in runner._pending_assignments(ledger,experiment.assignments)] == ["0"]
