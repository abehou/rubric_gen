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


def test_explicit_resume_preserves_contract_repairs_before_trailing_transport(tmp_path):
    runner, assignment, record, directory = fixture(tmp_path)
    first = directory / "attempt-001.json"
    returned = json.loads(first.read_text()) | {
        "status": "contract_invalid", "output": {"response_text": "returned"}
    }
    returned.pop("error_type")
    returned.pop("permanent")
    first.write_text(json.dumps(returned))
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record["automatic_recovery_exhausted"] is False
    assert directory.is_dir()
    assert sorted(path.name for path in directory.iterdir()) == ["attempt-001.json"]
    archived = list((tmp_path / "execution-attempts/a").glob("transport-*/request-key"))
    assert len(archived) == 1
    assert sorted(path.name for path in archived[0].iterdir()) == [
        "attempt-002.json", "attempt-003.json", "attempt-004.json"
    ]


def test_explicit_resume_recognizes_saved_wrapped_transport_from_older_classifier(tmp_path):
    runner, assignment, record, directory = fixture(tmp_path, category="structural")
    record.update(
        error_type="RubricProposerProviderError",
        error=f"enforcement: attempt allowance exhausted by transport at {directory}",
    )
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record["automatic_recovery_exhausted"] is False
    assert record["failure_category"] == "transient_connection"
    assert not directory.exists()


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
    {"status": "valid_result"},
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


def test_wrapped_transport_exhaustion_is_classified_for_explicit_resume():
    from rubric_gen.runtime.failures import failure_category
    from rubric_gen.submission_revision.evolution_provider import RubricProposerProviderError

    error = RubricProposerProviderError(
        "enforcement: attempt allowance exhausted by transport at /saved/request"
    )
    assert failure_category(error) == "transient_connection"


def test_explicit_resume_rearms_response_free_codex_turn(tmp_path):
    from rubric_gen.runtime.agents.codex_sessions import CodexProviderHealthError
    from rubric_gen.runtime.failures import failure_category

    runner = object.__new__(StudyRunner)
    runner.root = tmp_path
    runner.config = SimpleNamespace(resume=True, assignment_ids=None)
    runner.experiment = SimpleNamespace(execution_conditions=None)
    assignment = SimpleNamespace(
        assignment_id="a",
        condition_id="full",
        study_relative_path=Path("experiments/a"),
    )
    record = {
        "assignment_id": "a",
        "status": "failed",
        "attempt_count": 1,
        "automatic_attempt_count": 1,
        "automatic_recovery_exhausted": True,
        "error_type": "CodexProviderHealthError",
        "error": "Codex transport closed during an active turn",
        "failure_category": "structural",
    }
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record["automatic_recovery_exhausted"] is False
    assert record["automatic_attempt_count"] == 0
    assert record["failure_category"] == "transient_connection"
    assert list((tmp_path / "execution-attempts/a").glob("*.json"))
    assert failure_category(
        CodexProviderHealthError("Codex transport closed during an active turn")
    ) == "transient_connection"


def test_resume_honors_explicit_assignment_scope(tmp_path):
    runner, assignment, record, directory = fixture(tmp_path)
    runner.config.assignment_ids = ("another",)
    before = deepcopy(record)
    runner._rearm_transport_failures({"records": [record]}, [assignment])
    assert record == before
    assert directory.exists()
