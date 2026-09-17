"""A new explicit resume may retry response-free transport failures only."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision.study import StudyRunner


def fixture(tmp_path, *, category="transient_connection", status="failed", resume=True):
    runner = object.__new__(StudyRunner)
    runner.root = tmp_path
    runner.config = SimpleNamespace(resume=resume, assignment_ids=None)
    runner.experiment = SimpleNamespace(execution_conditions=None)
    assignment = SimpleNamespace(assignment_id="a", condition_id="full", study_relative_path=Path("experiments/a"))
    record = {"assignment_id": "a", "status": status, "attempt_count": 1,
              "automatic_attempt_count": 1, "automatic_recovery_exhausted": True,
              "failure_category": category}
    directory = tmp_path / "experiments/a/trace-defense-v2-requests/request-key"
    directory.mkdir(parents=True)
    for i in range(1, 5):
        (directory / f"attempt-{i:03d}.json").write_text(json.dumps({
            "attempt": i, "status": "provider_failure", "permanent": False,
            "error_type": "APIConnectionError", "request_sha256": "request-key"}))
    return runner, assignment, record, directory


def test_explicit_resume_archives_transport_only_and_preserves_success(tmp_path):
    runner, assignment, record, directory = fixture(tmp_path)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    valid = directory.parent / "completed-key"
    valid.mkdir()
    (valid / "result.json").write_text('{"unchanged": true}')
    completed = {"assignment_id": "b", "status": "completed"}
    manifest = {"records": [record, completed]}
    runner._rearm_transport_failures(manifest, [assignment])
    assert record["automatic_recovery_exhausted"] is False
    assert record["automatic_attempt_count"] == 0
    assert record["attempt_count"] == 1
    assert record["status"] == "failed"  # normal dispatch, not fabricated success
    assert completed == {"assignment_id": "b", "status": "completed"}
    assert not directory.exists()
    assert (valid / "result.json").read_text() == '{"unchanged": true}'
    archived = list((tmp_path / "execution-attempts/a").glob("transport-*/request-key"))
    assert len(archived) == 1
    assert {p.name: p.read_bytes() for p in archived[0].iterdir()} == before
    assert list((tmp_path / "execution-attempts/a").glob("*.json"))
    runner._rearm_transport_failures(manifest, [assignment])
    assert len(list((tmp_path / "execution-attempts/a").glob("transport-*"))) == 1


@pytest.mark.parametrize("overrides", [
    {"category": "authentication"}, {"category": "billing"},
    {"category": "configuration"}, {"category": "structural"},
    {"status": "completed"}, {"status": "invalid"}, {"resume": False},
])
def test_resume_does_not_rearm_other_failures_or_completed(tmp_path, overrides):
    runner, assignment, record, directory = fixture(tmp_path, **overrides)
    before = deepcopy(record)
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record == before
    assert directory.exists()


@pytest.mark.parametrize("change", [
    {"status": "contract_invalid"}, {"status": "valid_result"},
    {"permanent": True}, {"output": {"response_text": "returned response"}},
    {"error_type": "AuthenticationError"},
])
def test_resume_never_discards_returned_or_nontransport_attempts(tmp_path, change):
    runner, assignment, record, directory = fixture(tmp_path)
    path = directory / "attempt-001.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | change))
    before = deepcopy(record)
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record == before
    assert directory.exists()


def test_resume_honors_explicit_assignment_scope(tmp_path):
    runner, assignment, record, directory = fixture(tmp_path)
    runner.config.assignment_ids = ("another",)
    before = deepcopy(record)
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record == before
    assert directory.exists()
