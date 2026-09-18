"""Focused provider-free tests for the private Results40 execution bundle."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from rubric_gen.runtime import capacity
from rubric_gen.runtime.audit_execution import AuditExecutor, audit_owner
from rubric_gen.runtime.capacity import reservation
from rubric_gen.submission_revision.experiment import load_experiment

BUNDLE = Path(__file__).resolve().parent


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BUNDLE / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(BUNDLE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(BUNDLE))
    return module


def test_exact_membership_and_scientific_identity():
    membership = json.loads((BUNDLE / "membership.json").read_text())
    tasks = membership["new20"]
    assert len(tasks) == len(set(tasks)) == 20
    assert membership["new_assignments"] == 240
    conditions = tuple(membership["conditions"])
    assignments = 0
    seen_conditions = set()
    for task in tasks:
        for kind in ("static", "trace"):
            experiment = load_experiment(BUNDLE / "configs" / f"{task}-{kind}.yaml")
            assert experiment.task_ids == (task,)
            assert experiment.replicates == 3
            assert tuple(experiment.outcome_audit["models"]) == ("gpt-5.6-sol", "claude-opus-5")
            if kind == "trace":
                assert experiment.protocol["red_team_trace_version"] == (
                    "attack_defense_v2.1_execution_verified_proactive_provenance"
                )
                assert experiment.protocol["rubric_proposer_reasoning_effort_by_stage"] == {"diagnosis": "high"}
            else:
                assert experiment.protocol.get("red_team_trace_version") is None
            assert experiment.red_team_agent_config().reasoning_effort == "low"
            assert all(experiment.solver_config(s).reasoning_effort == "low" for s in experiment.solver_ids)
            assert all("dropout" not in a.condition_id for a in experiment.execution_assignments)
            seen_conditions.update(experiment.execution_conditions)
            assignments += len(experiment.execution_assignments)
    assert seen_conditions == set(conditions)
    assert assignments == 240


def test_babel_wrapper_creates_job_local_codex_sandbox_alias(tmp_path):
    common = BUNDLE / "common.sbatch"
    script = (
        "set -euo pipefail\n"
        f"export SLURM_JOB_ID=123 SLURM_TMPDIR={tmp_path / 'tmp'}\n"
        f"source {common}\n"
        "test -L \"$CODEX_HELPER_BIN/codex-linux-sandbox\"\n"
        "test -x \"$CODEX_HELPER_BIN/codex-linux-sandbox\"\n"
        "test \"$(command -v codex-linux-sandbox)\" = "
        "\"$CODEX_HELPER_BIN/codex-linux-sandbox\"\n"
        "test \"$(readlink -f \"$CODEX_HELPER_BIN/codex-linux-sandbox\")\" = "
        "\"$CODEX_SANDBOX_BINARY\"\n"
    )
    subprocess.run(["bash", "-c", script], cwd=BUNDLE.parents[1], check=True)


def test_revision_orchestrator_caps_ten_shards_of_six(monkeypatch, tmp_path):
    module = _module("trace_result40_run_test", "run.py")
    monkeypatch.setenv("SLURM_JOB_ID", "123")
    monkeypatch.setattr(module, "RUN", tmp_path)
    monkeypatch.setattr(module, "clean_commit", lambda: "source")
    active = 0
    peak = 0
    guard = threading.Lock()

    def fake_stage(task, kind, stage, workers, log):
        nonlocal active, peak
        assert stage == "revise" and workers == 6
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with guard:
            active -= 1
        return {"task_id": task, "shard": kind, "stage": stage, "exit_code": 0}

    monkeypatch.setattr(module, "uv_stage", fake_stage)
    monkeypatch.setattr(module, "complete_shard", lambda task, kind: [{}] * 6)
    monkeypatch.setattr(module, "validate_task_match", lambda task: None)
    monkeypatch.setattr(module, "experiment", lambda task, kind: type("E", (), {"experiment_id": f"{task}-{kind}"})())
    monkeypatch.setattr(module, "sha", lambda path: "0" * 64)
    owner = tmp_path / "owner"
    owner.mkdir()
    module.execute(owner)
    assert peak == 10
    receipt = json.loads((tmp_path / "revision-completion.json").read_text())
    assert receipt["assignment_count"] == 240


def test_revision_recovery_can_reduce_shard_concurrency(monkeypatch, tmp_path):
    module = _module("trace_result40_recovery_test", "run.py")
    monkeypatch.setenv("SLURM_JOB_ID", "456")
    monkeypatch.setenv("RESULT40_SHARD_WORKERS", "1")
    monkeypatch.setenv("RESULT40_ASSIGNMENT_WORKERS", "1")
    monkeypatch.setattr(module, "RUN", tmp_path)
    monkeypatch.setattr(module, "clean_commit", lambda: "source")
    active = 0
    peak = 0
    guard = threading.Lock()

    def fake_stage(task, kind, stage, workers, log):
        nonlocal active, peak
        assert stage == "revise" and workers == 1
        with guard:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with guard:
            active -= 1
        return {"task_id": task, "shard": kind, "stage": stage, "exit_code": 0}

    monkeypatch.setattr(module, "uv_stage", fake_stage)
    monkeypatch.setattr(module, "complete_shard", lambda task, kind: [{}] * 6)
    monkeypatch.setattr(module, "validate_task_match", lambda task: None)
    monkeypatch.setattr(module, "experiment", lambda task, kind: type("E", (), {"experiment_id": f"{task}-{kind}"})())
    monkeypatch.setattr(module, "sha", lambda path: "0" * 64)
    owner = tmp_path / "owner"
    owner.mkdir()
    module.execute(owner)
    assert peak == 1
    status = json.loads((tmp_path / "revision-status.json").read_text())
    assert status["shard_workers"] == 1
    assert status["maximum_assignment_workers"] == 1


def test_audit_partitions_allow_sixty_sol_and_sixty_opus(monkeypatch, tmp_path):
    monkeypatch.setattr(capacity, "policy", lambda: {
        "version": 1,
        "aggregate_concurrency": 60,
        "audit_studies": 1,
        "audit_provider_concurrency": {"openai": 60, "anthropic": 60},
        "coordination_dir": str(tmp_path / "runtime"),
    })
    release = threading.Event()
    condition = threading.Condition()
    active = {"openai": 0, "anthropic": 0}
    peak = {"openai": 0, "anthropic": 0, "total": 0}

    def operation(model):
        provider = "anthropic" if model.startswith("claude") else "openai"
        with reservation():
            with condition:
                active[provider] += 1
                peak[provider] = max(peak[provider], active[provider])
                peak["total"] = max(peak["total"], sum(active.values()))
                condition.notify_all()
            assert release.wait(10)
            with condition:
                active[provider] -= 1
        return model

    with audit_owner(tmp_path / "audit"):
        with AuditExecutor(120, ("gpt-5.6-sol", "claude-opus-5")) as pool:
            futures = []
            for _ in range(61):
                futures.append(pool.submit(operation, "gpt-5.6-sol", model="gpt-5.6-sol"))
                futures.append(pool.submit(operation, "claude-opus-5", model="claude-opus-5"))
            with condition:
                assert condition.wait_for(lambda: active == {"openai": 60, "anthropic": 60}, timeout=10)
            assert peak == {"openai": 60, "anthropic": 60, "total": 120}
            release.set()
            assert len([future.result(10) for future in futures]) == 122
