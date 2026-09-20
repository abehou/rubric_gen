import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "experiments/trace-v21-execution-verified-provenance-result40/rearm_audit_invalid.py"
SPEC = importlib.util.spec_from_file_location("result40_audit_rearm", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(tmp_path: Path, *, completed=False, category="invalid_response", error=None):
    error = error or "FullRubricJudgeError: rubric criteria_text must contain exactly 6 criterion lines"
    stage = tmp_path / "audit/scope/rubric_score"
    key = "a" * 32
    artifact = stage / "artifacts" / key
    attempts = artifact / "evaluations/s000/rubric/attempt.attempts"
    attempts.mkdir(parents=True)
    for number in (1, 2, 3):
        (attempts / f"attempt-{number:03d}.json").write_text(json.dumps({
            "attempt": number,
            "failure_category": category,
            "error": error,
        }))
        (attempts / f"attempt-{number:03d}.response.json").write_text("{}")
        (attempts.parent / f"failed-attempt-{number:03d}.json").write_text(json.dumps({
            "attempt": number,
            "error_type": "FullRubricJudgeError",
            "error": error.removeprefix("FullRubricJudgeError: "),
        }))
    if completed:
        completed_root = attempts.parent / "attempt"
        completed_root.mkdir()
        (completed_root / "evaluation.json").write_text("{}")
    (stage / "summary.json").write_text(json.dumps({
        "status": "incomplete",
        "judge_failures": [{
            "model": "claude-opus-5",
            "reason": "judge-failed",
            "error_type": "RuntimeError",
            "judgment_key": key,
        }],
    }))
    return tmp_path / "audit", stage, artifact


def test_archives_only_exhausted_cardinality_failure(tmp_path):
    root, stage, artifact = fixture(tmp_path)
    receipt = tmp_path / "receipt.json"
    result = MODULE.run(root, receipt)
    assert result["provider_calls"] == 0
    assert result["request_semantics_changed"] is False
    assert result["rearmed_judgments"] == 1
    assert not artifact.exists()
    archived = Path(result["actions"][0]["archive"])
    assert archived.is_dir()
    assert len(list(archived.rglob("attempt-*.response.json"))) == 3
    assert json.loads(receipt.read_text())["rearmed_judgments"] == 1


def test_ignores_unrelated_failure_and_rearms_reviewed_failure(tmp_path):
    root, stage, artifact = fixture(tmp_path)
    summary = json.loads((stage / "summary.json").read_text())
    summary["judge_failures"].append({
        "model": "gpt-5.6-sol",
        "reason": "judge-failed",
        "error_type": "RuntimeError",
        "judgment_key": "b" * 32,
    })
    (stage / "summary.json").write_text(json.dumps(summary))
    result = MODULE.run(root, tmp_path / "receipt.json")
    assert result["rearmed_judgments"] == 1
    assert not artifact.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"completed": True},
        {"category": "transient_provider"},
        {"error": "FullRubricJudgeError: some other invalid response"},
    ],
)
def test_refuses_unreviewed_or_completed_failures(tmp_path, kwargs):
    root, _, artifact = fixture(tmp_path, **kwargs)
    with pytest.raises(RuntimeError):
        MODULE.run(root, tmp_path / "receipt.json")
    assert artifact.is_dir()
