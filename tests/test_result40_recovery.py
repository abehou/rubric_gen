"""Focused provider-free checks for Results40 response-free recovery."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


MODULE = (
    Path(__file__).resolve().parents[1]
    / "experiments/trace-v21-execution-verified-provenance-result40/reconcile_recovery.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("result40_reconcile_test", MODULE)
    assert spec and spec.loader
    result = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(MODULE.parent))
    try:
        spec.loader.exec_module(result)
    finally:
        sys.path.remove(str(MODULE.parent))
    return result


def _fixture(tmp_path: Path, *, error: str = "Codex transport closed during an active turn"):
    study = tmp_path / "study"
    run = study / "experiments/case"
    live = tmp_path / "live"
    home = live / "workspace/.agent-state/codex"
    home.mkdir(parents=True)
    (home / "tmp").symlink_to(tmp_path / "gone-node-runtime")
    backup = home / ".tmp-preserved-one"
    backup.mkdir()
    (backup / "evidence").write_text("preserved")
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"live_workspace_dir": str(live / "workspace")}))
    record = {
        "assignment_id": "assignment",
        "experiment_dir": "experiments/case",
        "status": "failed",
        "error_type": "CodexProviderHealthError",
        "error": error,
        "failure_category": "structural",
        "automatic_recovery_exhausted": True,
        "automatic_attempt_count": 1,
    }
    (study / "study.json").write_text(json.dumps({"records": [record]}))
    return study, live, home


def test_reconcile_restores_interrupted_tmp_and_rearms_exact_transport(tmp_path):
    module = _module()
    study, live, home = _fixture(tmp_path)
    result = module.reconcile_study(study, live, apply=True)
    assert result["rearmed"] == ["assignment"]
    assert result["tmp_actions"][0]["action"] == "restore_backup"
    assert not (home / "tmp").is_symlink()
    assert (home / "tmp/evidence").read_text() == "preserved"
    record = json.loads((study / "study.json").read_text())["records"][0]
    assert record["automatic_recovery_exhausted"] is False
    assert record["automatic_attempt_count"] == 0


def test_reconcile_preserves_nonmatching_failure_budget(tmp_path):
    module = _module()
    study, live, _ = _fixture(tmp_path, error="different provider failure")
    result = module.reconcile_study(study, live, apply=False)
    assert result["rearmed"] == []
    record = json.loads((study / "study.json").read_text())["records"][0]
    assert record["automatic_recovery_exhausted"] is True


def test_reconcile_rearms_exact_interrupted_tmp_start_without_manifest_workspace(tmp_path):
    module = _module()
    study, live, home = _fixture(tmp_path)
    manifest = json.loads((study / "experiments/case/manifest.json").read_text())
    manifest.pop("live_workspace_dir")
    (study / "experiments/case/manifest.json").write_text(json.dumps(manifest))
    ledger = json.loads((study / "study.json").read_text())
    temporary = home / "tmp"
    ledger["records"][0]["error"] = (
        "Codex app-server start failed after 2 attempts: TransportClosedError: stderr_tail="
        "raise RuntimeError(\"Codex tmp requires terminal-owner reconciliation: \" + str(original))\n"
        "RuntimeError: "
        + module.TMP_ERROR
        + str(temporary)
    )
    (study / "study.json").write_text(json.dumps(ledger))
    result = module.reconcile_study(study, live, apply=True)
    assert result["rearmed"] == ["assignment"]
    assert result["tmp_actions"][0]["tmp"] == str(temporary)
    assert not temporary.is_symlink()
    assert (temporary / "evidence").read_text() == "preserved"


def test_reconcile_refuses_live_tmp_target(tmp_path):
    module = _module()
    study, live, home = _fixture(tmp_path)
    target = tmp_path / "gone-node-runtime"
    target.mkdir()
    try:
        module.reconcile_study(study, live, apply=True)
    except RuntimeError as error:
        assert "still has a live Codex temporary target" in str(error)
    else:
        raise AssertionError("live temporary owner must be preserved")
    assert (home / "tmp").is_symlink()


def test_recovery_only_uses_measured_memory_profile_and_audit_stays_frozen():
    bundle = MODULE.parent
    assert "#SBATCH --mem=160G" in (bundle / "recover.sbatch").read_text()
    assert "#SBATCH --mem=256G" in (bundle / "audit.sbatch").read_text()
    assert '"memory_mb": int(os.environ["SLURM_MEM_PER_NODE"])' in (bundle / "run.py").read_text()
