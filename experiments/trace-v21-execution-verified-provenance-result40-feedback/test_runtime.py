"""Focused provider-free checks for the Results40 feedback expansion."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys

import yaml


BUNDLE = Path(__file__).resolve().parent
MEMBERSHIP = json.loads((BUNDLE / "membership.json").read_text())
TASKS = tuple(MEMBERSHIP["new20"])
OLD20 = tuple(MEMBERSHIP["old20"])
PANEL = ["gpt-5.6-sol", "gemini-3.8-flash"]
CANDIDATE = "attack_defense_v2.1_execution_verified_proactive_provenance"


def config(task: str, kind: str) -> dict:
    return yaml.safe_load((BUNDLE / "configs" / f"{task}-{kind}.yaml").read_text())


def test_membership_and_scope() -> None:
    assert len(TASKS) == 20
    assert not set(TASKS) & set(OLD20)
    assert len(tuple((task, kind) for task in TASKS for kind in ("static", "trace"))) == 40
    assert sum(
        len(config(task, kind)["execution_conditions"]) * 3
        for task in TASKS for kind in ("static", "trace")
    ) == 240


def test_scientific_conditions_and_inputs() -> None:
    for task in TASKS:
        static = config(task, "static")
        trace = config(task, "trace")
        assert static["tasks"] == trace["tasks"] == [task]
        assert static["dag"]["seed"]["output_dir"] == trace["dag"]["seed"]["output_dir"]
        assert static["dag"]["paraphrase"]["output_dir"] == trace["dag"]["paraphrase"]["output_dir"]
        assert static["execution_conditions"] == [
            "semi-static",
            "score-only-static",
        ]
        assert trace["execution_conditions"] == [
            "semi-red-team-trace-execution-provenance-high-proposer",
            "score-only-red-team-trace-execution-provenance-high-proposer",
        ]
        assert "pretreatment_source" not in static
        source = trace["pretreatment_source"]["study_dir"]
        assert source.startswith((
            "/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/",
            "/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/",
        ))
        assert trace["protocol"]["red_team_trace_version"] == CANDIDATE
        assert trace["protocol"]["rubric_proposer_reasoning_effort_by_stage"] == {
            "diagnosis": "high"
        }
        assert "red_team_trace_version" not in static["protocol"]
        for payload in (static, trace):
            assert payload["randomization"] == {"seed": 20260820, "replicates": 3}
            assert payload["protocol"]["min_revisions"] == 5
            assert payload["protocol"]["max_revisions"] == 10
            assert payload["outcome_audit"]["models"] == PANEL
            assert payload["execution_audit_models"] == PANEL
            assert payload["seed_generator"]["reasoning_effort"] == "low"
            assert payload["red_team_generator"]["reasoning_effort"] == "low"
            assert all(row["reasoning_effort"] == "low" for row in payload["solvers"])
            assert all("dropout" not in row["condition_id"] for row in payload["conditions"])


def test_runtime_partitions() -> None:
    runtime = json.loads((BUNDLE / "runtime.json").read_text())
    assert runtime["aggregate_concurrency"] == 60
    assert runtime["audit_studies"] == 3
    assert runtime["audit_provider_concurrency"] == {
        "openai": 60,
        "anthropic": 60,
        "google": 60,
    }


def test_execution_and_audit_credentials_are_scoped(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    spec = importlib.util.spec_from_file_location("result40_feedback_run", BUNDLE / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.credential_keys("execute") == ("OPENAI_API_KEY",)
    assert module.credential_keys("audit") == ("OPENAI_API_KEY", "GEMINI_API_KEY")
