"""Focused provider-free checks for the Results40 feedback expansion."""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path
import sys
import tempfile

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
    assert module.credential_keys("audit-opus-complete") == ("ANTHROPIC_API_KEY",)
    assert module.OPUS_PANEL == ("claude-opus-5",)


def test_partial_opus_launcher_uses_frozen_runner() -> None:
    launcher = (BUNDLE / "opus-complete.sbatch").read_text()
    assert "#SBATCH --cpus-per-task=32" in launcher
    assert "run.py audit-opus-complete" in launcher


def test_revision_recovery_is_bounded_and_uses_local_codex_cache(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    spec = importlib.util.spec_from_file_location("result40_feedback_recovery", BUNDLE / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    monkeypatch.delenv("RESULT40_RECOVERY_PASSES", raising=False)
    assert module.revision_recovery_passes() == 3
    monkeypatch.setenv("RESULT40_RECOVERY_PASSES", "1")
    assert module.revision_recovery_passes() == 1
    monkeypatch.setenv("RESULT40_RECOVERY_PASSES", "4")
    try:
        module.revision_recovery_passes()
    except RuntimeError as error:
        assert "between 1 and 3" in str(error)
    else:
        raise AssertionError("unbounded recovery passes were accepted")

    assert "export RUBRIC_GEN_CODEX_LOCAL_CACHE=1" in (BUNDLE / "common.sbatch").read_text()
    assert "#SBATCH --mem=512G" in (BUNDLE / "revise.sbatch").read_text()
    rearm = (BUNDLE / "rearm_operational.sbatch").read_text()
    assert "recover_quota_failures.py" in rearm
    assert "--apply" in rearm


def test_quota_recovery_only_rearms_response_free_requests(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import recover_quota_failures as recovery

    with tempfile.TemporaryDirectory() as raw:
        run = Path(raw)
        study = run / "study" / "da-x" / "trace" / "experiment"
        request = study / "workspace" / "trace-defense-v2-requests" / "request"
        request.mkdir(parents=True)
        (request / "attempt-001.json").write_text(json.dumps({
            "status": "provider_failure",
            "permanent": False,
            "error_type": "OSError",
            "error": "[Errno 122] Disk quota exceeded",
        }))
        (study / "study.json").write_text(json.dumps({"records": [{
            "assignment_id": "assignment",
            "experiment_dir": "workspace",
            "status": "failed",
            "error_type": "RubricProposerProviderError",
            "automatic_recovery_exhausted": True,
            "automatic_attempt_count": 1,
        }]}))
        planned = recovery.plan(run)
        assert len(planned) == 1
        receipt = recovery.apply_recovery(run, planned)
        assert receipt.is_file()
        ledger = json.loads((study / "study.json").read_text())
        record = ledger["records"][0]
        assert record["automatic_recovery_exhausted"] is False
        assert record["automatic_attempt_count"] == 0
        assert not request.exists()


def test_quota_recovery_rejects_saved_provider_output(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import recover_quota_failures as recovery

    with tempfile.TemporaryDirectory() as raw:
        request = Path(raw) / "trace-defense-v2-requests" / "request"
        request.mkdir(parents=True)
        (request / "attempt-001.json").write_text(json.dumps({
            "status": "provider_failure",
            "permanent": False,
            "error_type": "OSError",
            "error": "[Errno 122] Disk quota exceeded",
            "output": {"response_text": "must be preserved"},
        }))
        try:
            recovery.response_free_quota_requests(Path(raw))
        except RuntimeError as error:
            assert "not an exact response-free operational failure" in str(error)
        else:
            raise AssertionError("saved provider output was accepted as response-free")


def test_quota_recovery_accepts_exact_response_free_missing_key(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import recover_quota_failures as recovery

    attempt = {
        "status": "provider_failure",
        "permanent": False,
        "error_type": "RuntimeError",
        "error": (
            "OPENAI_API_KEY must be set for the "
            "attack_defense_v2.1_execution_verified_proactive_provenance"
        ),
    }
    assert recovery._recoverable_operational_failure(attempt)
    attempt["error"] = "some other runtime failure"
    assert not recovery._recoverable_operational_failure(attempt)


def test_quota_recovery_accepts_only_exact_response_free_credit_exhaustion(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import recover_quota_failures as recovery

    attempt = {
        "status": "provider_failure",
        "permanent": False,
        "error_type": "RateLimitError",
        "error": (
            "Error code: 429 - {'error': {'message': 'You have no credits remaining. "
            "Add credits to continue using the API.', 'type': 'insufficient_quota', "
            "'param': None, 'code': 'credit_balance_exhausted'}}"
        ),
    }
    assert recovery._recoverable_operational_failure(attempt)
    assert not recovery._recoverable_operational_failure({
        **attempt,
        "error": attempt["error"].replace("credit_balance_exhausted", "rate_limit_exceeded"),
    })
    assert not recovery._recoverable_operational_failure({
        **attempt,
        "result": {"response_text": "must remain preserved"},
    })


def test_runtime_recovery_is_limited_to_pre_turn_startup_failure(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import reconcile_runtime_failures as recovery

    record = {
        "status": "failed",
        "automatic_recovery_exhausted": True,
        "error_type": "CodexProviderHealthError",
        "error": (
            "Codex app-server start failed after 2 attempts: "
            "TransportClosedError: Codex process closed stdout"
        ),
    }
    assert recovery._response_free_startup_failure(record)
    record["error"] = "Codex transport closed during an active turn"
    assert not recovery._response_free_startup_failure(record)


def test_runtime_recovery_restores_only_stale_owned_cli_tmp(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import reconcile_runtime_failures as recovery

    with tempfile.TemporaryDirectory() as raw:
        workspace = Path(raw) / "workspace"
        temporary = workspace.parent / ".agent-state/codex/tmp"
        temporary.parent.mkdir(parents=True)
        backup = temporary.parent / ".tmp-preserved-test"
        backup.mkdir()
        temporary.symlink_to(Path(raw) / "missing-cli-tmp", target_is_directory=True)
        action = recovery._reconcile_cli_tmp(
            "assignment", workspace, apply=True
        )
        assert action is not None
        assert action["action"] == "restore_backup"
        assert temporary.is_dir() and not temporary.is_symlink()
        assert not backup.exists()


def test_runtime_recovery_archives_reconstructible_workspace_restore(monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(BUNDLE.parents[1] / "src"))
    monkeypatch.syspath_prepend(str(BUNDLE))
    import reconcile_runtime_failures as recovery

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        recovery.LIVE = root
        experiment = root / "experiment"
        experiment.mkdir()
        workspace = root / "live" / "workspace"
        restored = workspace.parent / "workspace-restore"
        restored.mkdir(parents=True)
        (restored / "partial").write_text("preserved")
        record = {
            "assignment_id": "assignment",
            "error_type": "RuntimeError",
            "error": recovery.RESTORE_ERROR + str(restored),
        }
        action = recovery._archive_stale_restore(
            record, experiment, workspace, "stamp", apply=True
        )
        assert action is not None
        assert not restored.exists()
        archive = Path(str(action["archive"]))
        assert (archive / "partial").read_text() == "preserved"
