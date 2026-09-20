"""Focused provider-free tests for the private Results40 execution bundle."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

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


def test_completed_shard_reopens_audit_targets_without_rehashing_workspaces(
    monkeypatch, tmp_path
):
    module = _module("trace_result40_completion_test", "run.py")
    study = tmp_path / "study"
    study.mkdir()
    (study / "study.json").write_text("{}")
    identifiers = tuple(f"assignment-{index}" for index in range(6))
    rows = [
        {"assignment_id": identifier, "status": "completed"}
        for identifier in identifiers
    ]
    experiment = SimpleNamespace(
        dag={
            "revise": {"output_dir": str(study)},
            "paraphrase": {"output_dir": str(tmp_path / "paraphrase")},
            "detect": {"output_dir": str(tmp_path / "detect")},
        }
    )
    sources = object()
    observed = {}
    monkeypatch.setattr(module, "experiment", lambda task, kind: experiment)
    monkeypatch.setattr(module, "terminal_records", lambda exp, ledger: rows)
    monkeypatch.setattr(
        module, "resolve_study_sources", lambda root, exp: sources
    )

    def fake_targets(config, received_sources):
        observed.update(config=config, sources=received_sources)
        return tuple(SimpleNamespace(assignment_id=value) for value in identifiers)

    monkeypatch.setattr(module, "load_evaluation_targets", fake_targets)
    assert module.complete_shard("da-test", "trace") == rows
    assert observed["sources"] is sources
    assert observed["config"].study_dir == study
    assert observed["config"].max_concurrency == 6


def test_audit_partitions_allow_sixty_sol_and_sixty_opus(monkeypatch, tmp_path):
    monkeypatch.setattr(capacity, "policy", lambda: {
        "version": 1,
        "aggregate_concurrency": 60,
        "audit_studies": 3,
        "audit_provider_concurrency": {
            "openai": 60,
            "anthropic": 60,
            "google": 4,
        },
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


def test_audit_partition_allows_gemini_only_panel(monkeypatch, tmp_path):
    monkeypatch.setattr(capacity, "policy", lambda: {
        "version": 1,
        "aggregate_concurrency": 60,
        "audit_studies": 3,
        "audit_provider_concurrency": {
            "openai": 60,
            "anthropic": 60,
            "google": 4,
        },
        "coordination_dir": str(tmp_path / "runtime"),
    })
    release = threading.Event()
    condition = threading.Condition()
    active = 0
    peak = 0

    def operation(model):
        nonlocal active, peak
        with reservation():
            with condition:
                active += 1
                peak = max(peak, active)
                condition.notify_all()
            assert release.wait(10)
            with condition:
                active -= 1
        return model

    with audit_owner(tmp_path / "audit"):
        with AuditExecutor(4, ("gemini-3.8-flash",)) as pool:
            futures = [
                pool.submit(operation, "gemini-3.8-flash", model="gemini-3.8-flash")
                for _ in range(5)
            ]
            with condition:
                assert condition.wait_for(lambda: active == 4, timeout=10)
            assert peak == 4
            release.set()
            assert len([future.result(10) for future in futures]) == 5


def test_audit_partitions_include_independent_gemini_capacity(monkeypatch, tmp_path):
    monkeypatch.setattr(capacity, "policy", lambda: {
        "version": 1,
        "aggregate_concurrency": 60,
        "audit_studies": 3,
        "audit_provider_concurrency": {
            "openai": 60,
            "anthropic": 60,
            "google": 4,
        },
        "coordination_dir": str(tmp_path / "runtime"),
    })
    release = threading.Event()
    condition = threading.Condition()
    active = {"openai": 0, "anthropic": 0, "google": 0}
    peak = {"openai": 0, "anthropic": 0, "google": 0, "total": 0}

    def operation(model):
        provider = (
            "anthropic" if model.startswith("claude")
            else "google" if model.startswith("gemini")
            else "openai"
        )
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

    models = ("gpt-5.6-sol", "claude-opus-5", "gemini-3.8-flash")
    with audit_owner(tmp_path / "audit"):
        with AuditExecutor(124, models) as pool:
            futures = [
                pool.submit(operation, model, model=model)
                for _ in range(61)
                for model in models
                if not model.startswith("gemini")
            ]
            futures.extend(
                pool.submit(operation, "gemini-3.8-flash", model="gemini-3.8-flash")
                for _ in range(5)
            )
            with condition:
                assert condition.wait_for(
                    lambda: active == {"openai": 60, "anthropic": 60, "google": 4},
                    timeout=10,
                )
            assert peak == {
                "openai": 60,
                "anthropic": 60,
                "google": 4,
                "total": 124,
            }
            release.set()
            assert len([future.result(10) for future in futures]) == 127


def test_gemini_scope_preserves_revision_experiment_identity(tmp_path):
    scope = _module("trace_result40_audit_scope_test", "audit_scope.py")
    task, kind = scope.SHARDS[0]
    source = scope.load_experiment(scope.config_path(task, kind))
    scoped = scope.scoped_experiment(
        scope.config_path(task, kind),
        models=scope.GEMINI_PANEL,
        output_dir=tmp_path / source.experiment_id,
    )
    assert scoped.experiment_id == source.experiment_id
    assert scoped.dag["revise"]["output_dir"] == source.dag["revise"]["output_dir"]
    assert tuple(scoped.outcome_audit["models"]) == ("gemini-3.8-flash",)
    assert scoped.dag["detect"]["output_dir"] == str(tmp_path / source.experiment_id)


def test_execution_configs_match_saved_study_identity():
    scope = _module("trace_result40_saved_identity_test", "audit_scope.py")
    for task, kind in scope.SHARDS:
        source = scope.config_path(task, kind)
        experiment = scope.load_experiment(source)
        study = Path(experiment.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        assert ledger["experiment_path"] == str(source)
        assert ledger["experiment_id"] == experiment.experiment_id


def test_old20_gemini_scopes_keep_exact_completed_studies():
    scope = _module("trace_result40_old20_audit_scope_test", "audit_scope.py")
    rows = scope.old20_gemini_scopes()
    assert {name for name, _ in rows} == {
        "old20-static-full-gemini",
        "old20-static-user-gemini",
        "old20-current-gemini",
    }
    for name, experiment in rows:
        assert tuple(experiment.outcome_audit["models"]) == ("gemini-3.8-flash",)
        assert Path(experiment.dag["revise"]["output_dir"]).is_dir()
        assert str(experiment.dag["detect"]["output_dir"]).startswith(
            "/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/"
            "audit-gemini/old20/"
        )
        expected = 120 if name == "old20-current-gemini" else 60
        assert len(experiment.execution_assignments) == expected
        if name.startswith("old20-static-"):
            from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
            from rubric_gen.submission_revision.evaluation.targets import (
                load_evaluation_targets,
            )
            from rubric_gen.submission_revision.source_resolution import (
                resolve_study_sources,
            )

            study = Path(experiment.dag["revise"]["output_dir"])
            sources = resolve_study_sources(study, experiment)
            assert len(sources.revisions) == 60
            first = sources.revisions[0]
            assert first.manifest["task_dir"] == str(
                first.producer.task_dir(first.assignment.task_id)
            )
            with scope.historical_revision_prompt(name, experiment):
                targets = load_evaluation_targets(EvaluationConfig(
                    experiment=experiment,
                    study_dir=study,
                    paraphrase_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
                    output_dir=Path(experiment.dag["detect"]["output_dir"]),
                    max_concurrency=60,
                    resume=True,
                ), sources)
            assert len(targets) == 60


def test_three_model_analysis_uses_equal_artifact_weights():
    analysis = _module("trace_result40_three_model_analysis_test", "analyze.py")
    assert analysis.PANELS == {
        "sol_opus": ("gpt-5.6-sol", "claude-opus-5"),
        "sol": ("gpt-5.6-sol",),
        "opus": ("claude-opus-5",),
        "gemini": ("gemini-3.8-flash",),
        "sol_opus_gemini": (
            "gpt-5.6-sol", "claude-opus-5", "gemini-3.8-flash"
        ),
    }
    rows = []
    for index, model in enumerate(analysis.THREE_MODEL_PANEL, start=1):
        row = {
            "cohort": "current_full",
            "artifact_id": "da-test--rep-001",
            "task_id": "da-test",
            "replicate": 1,
            "model": model,
            "initial_submission_sha256": "0" * 64,
        }
        for metric in analysis.METRICS:
            row[metric] = float(index)
        for window in analysis.WINDOWS:
            row[f"RH_{window}_decision"] = (
                "reward_hacking_detected" if index == 1
                else "abstain" if index == 2
                else "no_reward_hacking_detected"
            )
            row[f"RH_{window}_score"] = float(index)
        rows.append(row)
    summary = analysis.summarize_panel(
        rows, "current_full", analysis.THREE_MODEL_PANEL
    )
    assert summary["assignments"] == 1
    assert summary["auditor_rows"] == 3
    assert summary["metrics"]["W_minus_S"]["mean"] == 2.0
    assert summary["rh"]["full_trajectory"]["positive"] == 1
    assert summary["rh"]["full_trajectory"]["abstain"] == 1
    panel = analysis.panel_artifacts(
        rows, analysis.THREE_MODEL_PANEL, "sol_opus_gemini"
    )
    assert len(panel) == 1
    assert panel[0]["W_minus_S"] == 2.0
    assert panel[0]["RH_full_trajectory_positive_percent"] == 100 / 3
