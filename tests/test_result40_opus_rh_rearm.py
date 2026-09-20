import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "experiments/trace-v21-execution-verified-provenance-result40/rearm_opus_rh.py"
SPEC = importlib.util.spec_from_file_location("result40_opus_rh_rearm", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(tmp_path: Path, *, complete=False, error=MODULE.NO_JSON):
    root = tmp_path / "audit"
    evaluation = root / "task/direct_full_trajectory/evaluations/run"
    model_root = evaluation / "cases/case-1" / MODULE.MODEL
    model_root.mkdir(parents=True)
    response_ids = []
    for attempt in range(1, 4):
        response_id = f"response-{attempt}"
        response_ids.append(response_id)
        path = model_root / "chunk-001" / f"attempt-{attempt:03d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "attempt": attempt,
            "error": error,
            "remote_completion": "confirmed",
            "generation": {
                "requested_model": MODULE.MODEL,
                "response_id": response_id,
            },
        }))
    if complete:
        (model_root / "score.json").write_text("{}")
    (evaluation / "summary.json").write_text(json.dumps({
        "source": {"window": "full_trajectory"},
        "records": [{
            "model": MODULE.MODEL,
            "status": "failed",
            "failure_category": "structural",
            "error": f"direct request exhausted 3 attempts: {MODULE.NO_JSON}",
            "max_attempts": 3,
            "case_id": "case-1",
        }],
    }))
    return root, model_root, response_ids


def test_rearms_exact_reviewed_opus_rh_failure_and_preserves_evidence(tmp_path):
    root, model_root, response_ids = fixture(tmp_path)
    result = MODULE.run(root, tmp_path / "receipt.json", expected=1)
    assert result["provider_calls"] == 0
    assert result["request_semantics_changed"] is False
    assert result["rearmed_judgments"] == 1
    assert result["actions"][0]["response_ids"] == response_ids
    assert model_root.is_dir()
    assert not list(model_root.glob("chunk-*/attempt-*.json"))
    assert all(Path(path).is_file() for path in result["actions"][0]["archives"])


def test_refuses_completed_or_different_failure(tmp_path):
    root, _, _ = fixture(tmp_path, complete=True)
    with pytest.raises(RuntimeError, match="completed"):
        MODULE.run(root, tmp_path / "receipt.json", expected=1)
    root, _, _ = fixture(tmp_path / "other", error="different error")
    with pytest.raises(RuntimeError, match="reviewed"):
        MODULE.run(root, tmp_path / "other-receipt.json", expected=1)


def test_refuses_unexpected_failure_count(tmp_path):
    root, _, _ = fixture(tmp_path)
    with pytest.raises(RuntimeError, match="expected 17"):
        MODULE.run(root, tmp_path / "receipt.json")


def test_preserves_successful_chunks_and_rearms_empty_response(tmp_path):
    root, model_root, _ = fixture(tmp_path, error=MODULE.EMPTY_RESPONSE)
    failed = sorted(model_root.glob("chunk-*/attempt-*.json"))
    for attempt in failed:
        value = json.loads(attempt.read_text())
        value["generation"] = None
        value["remote_completion"] = "unknown"
        attempt.write_text(json.dumps(value))
    good = model_root / "chunk-000/attempt-001.json"
    good.parent.mkdir()
    good.write_text(json.dumps({
        "attempt": 1,
        "error": None,
        "remote_completion": "confirmed",
        "generation": {"requested_model": MODULE.MODEL, "response_id": "good"},
    }))
    summary = next(root.glob("**/summary.json"))
    value = json.loads(summary.read_text())
    value["records"][0]["error"] = f"recorded structural: {failed[-1]}"
    summary.write_text(json.dumps(value))
    result = MODULE.run(root, tmp_path / "receipt.json", expected=1)
    assert good.exists()
    assert result["actions"][0]["preserved_successful_chunks"] == 1
