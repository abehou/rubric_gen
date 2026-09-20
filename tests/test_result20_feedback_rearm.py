import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).parents[1]
BUNDLE = ROOT / "experiments/trace-v21-execution-verified-provenance-result20-feedback"
sys.path.insert(0, str(BUNDLE))
SPEC = importlib.util.spec_from_file_location("result20_feedback_opus_rearm", BUNDLE / "rearm_opus.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.remove(str(BUNDLE))


def direct_fixture(tmp_path: Path, *, completed: bool) -> Path:
    root = tmp_path / "audit"
    evaluation = root / "direct_full_trajectory/evaluations/run"
    model_root = evaluation / "cases/case-1" / MODULE.MODEL
    model_root.mkdir(parents=True)
    if completed:
        (model_root / "score.json").write_text("{}")
    else:
        attempt = model_root / "chunk-001/attempt-001.json"
        attempt.parent.mkdir()
        attempt.write_text(json.dumps({
            "error": "Your credit balance is too low to access the Anthropic API",
            "error_type": "BadRequestError",
        }))
    (evaluation / "summary.json").write_text(json.dumps({
        "records": [{
            "model": MODULE.MODEL,
            "case_id": "case-1",
            "status": "failed",
        }],
    }))
    return root


def test_skips_completed_score_from_stale_failed_summary(tmp_path):
    root = direct_fixture(tmp_path, completed=True)
    assert MODULE.direct_actions(root, tmp_path / "archive") == []


def test_rearms_only_saved_low_credit_attempt(tmp_path):
    root = direct_fixture(tmp_path, completed=False)
    actions = MODULE.direct_actions(root, tmp_path / "archive")
    assert len(actions) == 1
    assert actions[0]["kind"] == "direct_rh_attempt"


def test_rubric_failure_allowlist_is_narrow():
    assert MODULE.allowed_rubric_failure({
        "failure_category": "configuration",
        "error": "credit balance is too low",
    })
    assert MODULE.allowed_rubric_failure({
        "failure_category": "invalid_response",
        "error": "rubric criteria_text must contain exactly 6 criterion lines",
    })
    assert not MODULE.allowed_rubric_failure({
        "failure_category": "structural",
        "error": "different scientific failure",
    })
