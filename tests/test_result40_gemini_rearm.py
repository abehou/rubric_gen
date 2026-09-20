import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "experiments/trace-v21-execution-verified-provenance-result40/rearm_gemini_rate_limits.py"
SPEC = importlib.util.spec_from_file_location("result40_gemini_rearm", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def semantic_fixture(tmp_path: Path, *, error="Gemini API request failed with HTTP 429: RESOURCE_EXHAUSTED"):
    root = tmp_path / "audit-gemini"
    stage = root / "old20/static/rubric_score"
    key = "a" * 32
    attempts = stage / "artifacts" / key / "evaluations/s000/rubric/attempt.attempts"
    attempts.mkdir(parents=True)
    (attempts / "attempt-001.json").write_text(json.dumps({"attempt": 1, "error": error}))
    (stage / "summary.json").write_text(json.dumps({
        "status": "incomplete",
        "judge_failures": [{"model": MODULE.MODEL, "judgment_key": key}],
    }))
    return root, stage / "artifacts" / key


def direct_fixture(tmp_path: Path, *, error="Gemini API request failed with HTTP 429: Quota exceeded"):
    root = tmp_path / "audit-gemini"
    evaluation = root / "old20/static/direct_full_trajectory/evaluations/run"
    model_root = evaluation / "cases/case-1" / MODULE.MODEL
    good = model_root / "chunk-001/attempt-001.json"
    bad = model_root / "chunk-002/attempt-001.json"
    good.parent.mkdir(parents=True)
    bad.parent.mkdir(parents=True)
    good.write_text(json.dumps({"generation": {"text": "ok"}}))
    bad.write_text(json.dumps({"error": error}))
    (evaluation / "summary.json").write_text(json.dumps({
        "records": [{"model": MODULE.MODEL, "case_id": "case-1", "status": "failed"}],
    }))
    return root, good, bad


def test_rearms_only_failed_rate_limited_state_and_preserves_valid_chunks(tmp_path):
    root, artifact = semantic_fixture(tmp_path)
    _, good, bad = direct_fixture(tmp_path)
    result = MODULE.run(root, tmp_path / "receipt.json")
    assert result["provider_calls"] == 0
    assert result["request_semantics_changed"] is False
    assert result["rearmed_items"] == 2
    assert not artifact.exists()
    assert good.exists()
    assert not bad.exists()
    assert all(Path(action["archive"]).exists() for action in result["actions"])


def test_rearms_pre_request_capacity_seal_failure(tmp_path):
    root, artifact = semantic_fixture(
        tmp_path, error="shared capacity changed; refuse a split budget"
    )
    result = MODULE.run(root, tmp_path / "receipt.json")
    assert result["provider_calls"] == 0
    assert result["google_provider_concurrency"] == 60
    assert result["gemini_executor_workers"] == 4
    assert result["rearmed_items"] == 1
    assert not artifact.exists()


def test_rearms_semantic_failure_when_fatal_stage_wrote_no_summary(tmp_path):
    root, artifact = semantic_fixture(
        tmp_path, error="shared capacity changed; refuse a split budget"
    )
    (artifact.parents[1] / "summary.json").unlink()
    result = MODULE.run(root, tmp_path / "receipt.json")
    assert result["rearmed_items"] == 1
    assert result["actions"][0]["discovered_without_summary"] is True
    assert not artifact.exists()


def test_rearms_flat_semantic_attempts_without_summary_and_preserves_records(tmp_path):
    root = tmp_path / "audit-gemini"
    stage = root / "old20/static/absolute_score"
    failed_key = "b" * 32
    completed_key = "c" * 32
    failed = stage / "attempts" / failed_key
    completed_attempts = stage / "attempts" / completed_key
    failed.mkdir(parents=True)
    completed_attempts.mkdir(parents=True)
    error = "Gemini API request failed with HTTP 429: RESOURCE_EXHAUSTED"
    (failed / "attempt-001.json").write_text(json.dumps({"attempt": 1, "error": error}))
    (completed_attempts / "attempt-001.json").write_text(json.dumps({"attempt": 1}))
    records = stage / "records"
    records.mkdir()
    completed_record = records / f"{completed_key}.json"
    completed_record.write_text("{}")

    result = MODULE.run(root, tmp_path / "receipt.json")

    assert result["rearmed_items"] == 1
    assert result["actions"][0]["storage_layout"] == "flat_attempts"
    assert not failed.exists()
    assert completed_attempts.exists()
    assert completed_record.exists()


@pytest.mark.parametrize("fixture", [semantic_fixture, direct_fixture])
def test_refuses_non_rate_limit_failures(tmp_path, fixture):
    root, *_ = fixture(tmp_path, error="some other provider failure")
    with pytest.raises(RuntimeError):
        MODULE.run(root, tmp_path / "receipt.json")


def test_preserves_completed_direct_judgment_from_stale_failure_summary(tmp_path):
    root, good, _ = direct_fixture(tmp_path)
    (good.parents[1] / "score.json").write_text("{}")
    assert MODULE.direct_actions(root, tmp_path / "archive") == []
    assert (good.parents[1] / "score.json").exists()


def test_leaves_pre_attempt_direct_failure_for_native_missing_only_resume(tmp_path):
    root, _, bad = direct_fixture(tmp_path)
    bad.unlink()
    assert MODULE.direct_actions(root, tmp_path / "archive") == []
