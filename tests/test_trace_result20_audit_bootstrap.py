"""Focused checks for the Results20 audit execution wrapper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "experiments/trace-v21-execution-verified-provenance-result20"


def load_run_module():
    spec = importlib.util.spec_from_file_location(
        "trace_result20_run_test", BUNDLE / "run.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(BUNDLE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(BUNDLE))
    return module


def test_detect_runs_public_cli_in_process(monkeypatch):
    module = load_run_module()
    calls = []

    def fake_main(argv):
        calls.append(argv)
        return 0

    import rubric_gen.cli

    monkeypatch.setattr(rubric_gen.cli, "main", fake_main)
    module.detect_in_process(120)
    assert calls == [[
        "detect",
        "--experiment", str(module.CONFIG),
        "--max-concurrency", "120",
        "--resume",
    ]]


def test_audit_installs_reuse_before_detect(monkeypatch, tmp_path):
    module = load_run_module()
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    events = []
    owner = tmp_path / "owner"
    owner.mkdir()
    monkeypatch.setattr(module, "RUN", tmp_path / "run")
    study = tmp_path / "study"
    audit = tmp_path / "audit"
    experiment = SimpleNamespace(
        experiment_id="biomnibench-da-factorial-r10-682343156c5d",
        dag={
            "revise": {"output_dir": str(study)},
            "detect": {"output_dir": str(audit)},
        }
    )

    monkeypatch.setattr(
        module, "completed_revision_receipt", lambda value: events.append("receipt")
    )

    def install_reuse():
        events.append("reuse")
        return ["source"]

    def detect_in_process(workers):
        assert workers == 120
        assert events == ["receipt", "reuse"]
        events.append("detect")

    monkeypatch.setattr(module, "install_reuse", install_reuse)
    monkeypatch.setattr(module, "detect_in_process", detect_in_process)
    monkeypatch.setattr(module, "require_clean_source", lambda: "frozen-source")

    def check(*args, **kwargs):
        events.append("check")
        return {"assignment_count": 120}

    monkeypatch.setitem(sys.modules, "check_audit_coverage", SimpleNamespace(check=check))
    module.audit(experiment, owner)
    assert events == ["receipt", "reuse", "detect", "check"]
    assert (owner / "audit-reuse-sources.json").is_file()
