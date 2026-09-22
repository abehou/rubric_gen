import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
BUNDLE = ROOT / "experiments/trace-v21-execution-verified-provenance-result40-feedback"
sys.path.insert(0, str(BUNDLE))
SPEC = importlib.util.spec_from_file_location("result40_feedback_opus_rearm", BUNDLE / "rearm_opus.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.remove(str(BUNDLE))
for _name in ("make_configs", "prepare", "run"):
    sys.modules.pop(_name, None)


def test_rearms_only_exact_failed_cardinality_artifact(tmp_path):
    root = tmp_path / "audit"
    artifact = root / "rubric_score/artifacts/key"
    artifact.mkdir(parents=True)
    (artifact / "attempt-001.json").write_text(json.dumps({
        "failure_category": "invalid_response",
        "error": "rubric criteria_text must contain exactly 9 criterion lines",
    }))
    actions = MODULE.rubric_actions(root, tmp_path / "archive")
    assert len(actions) == 1
    assert actions[0]["kind"] == "rubric_score"


def test_preserves_completed_rubric_artifact(tmp_path):
    root = tmp_path / "audit"
    artifact = root / "rubric_score/artifacts/key"
    artifact.mkdir(parents=True)
    (root / "rubric_score/records").mkdir()
    (root / "rubric_score/records/key.json").write_text("{}")
    (artifact / "attempt-001.json").write_text(json.dumps({
        "failure_category": "invalid_response",
        "error": "rubric criteria_text must contain exactly 9 criterion lines",
    }))
    assert MODULE.rubric_actions(root, tmp_path / "archive") == []


def test_rejects_unreviewed_failure(tmp_path):
    root = tmp_path / "audit"
    artifact = root / "rubric_score/artifacts/key"
    artifact.mkdir(parents=True)
    (artifact / "attempt-001.json").write_text(json.dumps({
        "failure_category": "invalid_response",
        "error": "different structural failure",
    }))
    try:
        MODULE.rubric_actions(root, tmp_path / "archive")
    except RuntimeError as error:
        assert "unsupported missing Opus rubric failure" in str(error)
    else:
        raise AssertionError("unreviewed failure was accepted")
