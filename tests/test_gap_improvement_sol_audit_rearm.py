from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "experiments/trace-v21-result40-gap-improvement"
)


def load_module():
    path = BUNDLE / "rearm_historical_sol_audit.py"
    spec = importlib.util.spec_from_file_location("gap_sol_audit_rearm", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(BUNDLE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(BUNDLE))
    return module


def attempt(path: Path, *, category="billing", material=False, error=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "attempt": 1,
        "identity": {"model": "gpt-5.6-sol"},
        "category": category,
        "error_type": "APIError",
        "error": error or "You have no credits remaining: credit_balance_exhausted",
        "remote_completion": "unknown",
    }
    if material:
        value["generation"] = {"text": "provider output"}
    path.write_text(json.dumps(value))


def coverage(*stages: str) -> dict[str, object]:
    return {
        "stages": {
            name: {"missing": int(name in stages)}
            for name in (
                "rubric_score",
                "absolute_score",
                "pairwise_preference",
                "direct_full_trajectory",
                "direct_post_update",
                "direct_final_artifact",
                "direct_final_revision",
            )
        }
    }


def rubric_manifest(root: Path, keys: list[str]) -> None:
    stage = root / "rubric_score"
    stage.mkdir(parents=True, exist_ok=True)
    jobs = [
        {"semantic_key": key, "model": "gpt-5.6-sol"}
        for key in keys
    ]
    jobs.extend(
        {"semantic_key": f"gemini-{index}", "model": "gemini-3.8-flash"}
        for index in range(55)
    )
    while sum(job["model"] == "gpt-5.6-sol" for job in jobs) < 55:
        index = sum(job["model"] == "gpt-5.6-sol" for job in jobs)
        key = f"saved-{index}"
        jobs.append({"semantic_key": key, "model": "gpt-5.6-sol"})
        records = stage / "records"
        records.mkdir(exist_ok=True)
        (records / f"{key}.json").write_text("{}")
    (stage / "manifest.json").write_text(json.dumps({"predispatch_plan": {"jobs": jobs}}))


def test_plans_exact_nested_flat_and_direct_response_free_failures(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    root = tmp_path / "audit"
    attempt(
        root
        / "rubric_score/artifacts/rubric-key/evaluations/s/r/a.attempts/attempt-001.json"
    )
    rubric_manifest(root, ["rubric-key"])
    attempt(root / "absolute_score/attempts/absolute-key/attempt-001.json")
    attempt(
        root
        / "direct_final_artifact/evaluations/run/cases/revision-000001"
        / "gpt-5.6-sol/chunk-0/attempt-001.json",
        category="transient_provider",
    )
    monkeypatch.setattr(module, "saved_model_counts", lambda _root: {})
    monkeypatch.setattr(
        module,
        "model_coverage",
        lambda _counts, _model: coverage(
            "rubric_score", "absolute_score", "direct_final_artifact"
        ),
    )
    actions, missing, attempt_free = module.plan(root, tmp_path / "archive")
    assert missing["rubric_score"] == 1
    assert [action["stage"] for action in actions] == [
        "rubric_score",
        "absolute_score",
        "direct_final_artifact",
    ]
    assert sum(action["saved_attempts"] for action in actions) == 3
    assert attempt_free == {"rubric_score": []}
    assert all(
        attempt_row["provider_material"] is False
        for action in actions
        for attempt_row in action["attempts"]
    )


def test_refuses_attempt_with_provider_material(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    root = tmp_path / "audit"
    attempt(
        root / "absolute_score/attempts/absolute-key/attempt-001.json",
        material=True,
    )
    monkeypatch.setattr(module, "saved_model_counts", lambda _root: {})
    monkeypatch.setattr(
        module,
        "model_coverage",
        lambda _counts, _model: coverage("absolute_score"),
    )
    with pytest.raises(RuntimeError, match="provider material"):
        module.plan(root, tmp_path / "archive")


def test_accepts_only_exact_credit_error_when_category_is_structural(
    tmp_path: Path,
) -> None:
    module = load_module()
    accepted = tmp_path / "accepted.json"
    attempt(accepted, category="structural")
    assert module.response_free_operational_attempt(accepted)["category"] == "structural"
    refused = tmp_path / "refused.json"
    attempt(refused, category="structural", error="unrelated implementation failure")
    with pytest.raises(RuntimeError, match="not a reviewed response-free"):
        module.response_free_operational_attempt(refused)


def test_direct_plan_preserves_confirmed_generation_and_rearms_only_failure(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    root = tmp_path / "audit"
    model_root = (
        root
        / "direct_final_artifact/evaluations/run/cases/revision-000001"
        / "gpt-5.6-sol"
    )
    attempt(model_root / "chunk-0/attempt-001.json", material=True)
    attempt(model_root / "chunk-1/attempt-001.json")
    monkeypatch.setattr(module, "saved_model_counts", lambda _root: {})
    monkeypatch.setattr(
        module,
        "model_coverage",
        lambda _counts, _model: coverage("direct_final_artifact"),
    )
    rubric_manifest(root, [])
    actions, _missing, _attempt_free = module.plan(root, tmp_path / "archive")
    assert len(actions) == 1
    assert actions[0]["preserved_provider_attempts"] == 1
    assert actions[0]["sources"] == [
        str(model_root / "chunk-1/attempt-001.json")
    ]


def test_refuses_scope_that_does_not_equal_missing_inventory(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    root = tmp_path / "audit"
    root.mkdir()
    rubric_manifest(root, ["never-attempted"])
    monkeypatch.setattr(module, "saved_model_counts", lambda _root: {})
    monkeypatch.setattr(
        module,
        "model_coverage",
        lambda _counts, _model: coverage("rubric_score"),
    )
    actions, _missing, attempt_free = module.plan(root, tmp_path / "archive")
    assert actions == []
    assert attempt_free == {"rubric_score": ["never-attempted"]}


def test_refuses_residual_rubric_key_with_unreviewed_attempt(
    tmp_path: Path, monkeypatch
) -> None:
    module = load_module()
    root = tmp_path / "audit"
    rubric_manifest(root, ["residual"])
    path = (
        root
        / "rubric_score/artifacts/residual/evaluations/x/r/y.attempts/attempt-001.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"identity": {"model": "other-model"}}))
    monkeypatch.setattr(module, "saved_model_counts", lambda _root: {})
    monkeypatch.setattr(
        module,
        "model_coverage",
        lambda _counts, _model: coverage("rubric_score"),
    )
    with pytest.raises(RuntimeError, match="not attempt-free"):
        module.plan(root, tmp_path / "archive")
