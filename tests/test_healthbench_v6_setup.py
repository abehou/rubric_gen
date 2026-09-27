"""Offline checks of the selected Dev3 cohort, fresh outputs and frozen roles."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import yaml
import pytest

from rubric_gen.benchmarks.answer_only.dataset import render_rubric
from rubric_gen.submission_revision.experiment import load_experiment

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "experiments/healthbench-hard-local-mac"


def test_v6_changes_only_dataset_and_output_paths_from_v5():
    base = yaml.safe_load((HERE / "dev3-v5.yaml").read_text())
    new = yaml.safe_load((HERE / "dev3-v6.yaml").read_text())
    for field in ("tasks_dir", "dag"):
        assert base.pop(field) != new.pop(field)
    assert new == base
    experiment = load_experiment(HERE / "dev3-v6.yaml")
    assert len(experiment.assignments) == 36
    assert experiment.payload["protocol"]["min_revisions"] == 3
    assert experiment.payload["outcome_audit"]["models"] == ["gpt-6-luna"]


def test_v6_keeps_official_predicates_points_and_is_disjoint():
    dataset = ROOT / "data/healthbench-hard/rh-dev3-20260926-v6"
    manifest = json.loads((dataset / "manifest.json").read_text())
    ids = {t["source_id"] for t in manifest["tasks"]}
    assert ids == {
        "47a50742-10ba-462a-84bb-a119bfe360af",
        "d716ca0e-52b9-491b-92b4-1d74e450314c",
        "5f539a2c-85f4-4cc9-8790-e1b23d950954",
    }
    for previous in dataset.parent.glob("*/manifest.json"):
        if previous.parent == dataset:
            continue
        old_ids = {t["source_id"] for t in json.loads(previous.read_text())["tasks"]}
        assert ids.isdisjoint(old_ids), previous
    for task in manifest["tasks"]:
        path = dataset / task["task_id"]
        row = json.loads((path / "tests/source.json").read_text())["source_record"]
        assert len(row["rubrics"]) == 8
        assert (path / "tests/rubric.txt").read_text() == render_rubric(row, "healthbench-hard")
        for message in row["prompt"]:
            assert message["content"] in (path / "instruction.md").read_text()


def test_v6_launcher_scopes_native_stages_and_worker_credentials(monkeypatch):
    sys.path.insert(0, str(HERE))
    import run_dev3_v6 as launcher
    experiment = load_experiment(HERE / "dev3-v6.yaml")
    for stage in ("seed", "paraphrase", "revise", "detect"):
        command = launcher.stage_command(stage, experiment)
        assert command[0] == sys.executable
        assert command[4:6] == ["--experiment", str(HERE / "dev3-v6.yaml")]
        assert ("--resume" in command) == (stage in ("revise", "detect"))
        assert ("--assignment-workers" in command) == (stage == "revise")
        assert ("--study-dir" in command) == (stage == "detect")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-inherit")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-inherit")
    monkeypatch.setenv("RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY", "should-not-inherit")
    env = launcher.worker_environment("dummy-local-key")
    assert env["OPENAI_API_KEY"] == env["CODEX_API_KEY"] == "dummy-local-key"
    assert "ANTHROPIC_API_KEY" not in env and "RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY" not in env
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:18765/v1"
    assert launcher.BUDGET_USD == 3


@pytest.mark.parametrize("complete_remaining", [False, True])
def test_v6_launcher_runs_authorized_stages_and_preserves_ledger(tmp_path, monkeypatch, complete_remaining):
    sys.path.insert(0, str(HERE))
    import run_dev3_v6 as launcher
    experiment = load_experiment(HERE / "dev3-v6.yaml")
    monkeypatch.setattr(launcher, "OUTPUT", tmp_path)
    monkeypatch.setattr(launcher, "__file__", "experiments/healthbench-hard-local-mac/run_dev3_v6.py")
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    (study_dir / "study.json").write_text('{"status":"failed"}')
    if complete_remaining:
        ledger = launcher.Ledger(tmp_path / "budget.json", 3.)
        ledger.state.update(spent_usd=1.8, stopped=True, completed=900)
        ledger.save()
    monkeypatch.setattr(launcher, "load_experiment", lambda _: SimpleNamespace(
        assignments=experiment.assignments, outcome_audit=experiment.outcome_audit,
        payload=experiment.payload, experiment_id=experiment.experiment_id,
        dag={**experiment.dag, "seed": {"output_dir": str(tmp_path / "seeds")},
             "revise": {"output_dir": str(study_dir)}},
    ))
    monkeypatch.setattr(launcher, "dotenv_values", lambda _: {"OPENAI_API_KEY": "sk-test-IfoA"})
    monkeypatch.setattr(launcher, "start_proxy", lambda *args: SimpleNamespace(
        shutdown=lambda: None, server_close=lambda: None,
    ))
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs["env"]["RUBRIC_GEN_OPENAI_REASONING_EFFORT"]))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    monkeypatch.setattr(launcher.subprocess, "check_output", lambda *a, **k: "head" if k.get("text") else b"diff")
    launcher.main(complete_remaining=complete_remaining)
    assert [c[0][3] for c in calls] == (["revise", "detect"] if complete_remaining else ["seed", "paraphrase", "revise", "detect"])
    assert [c[1] for c in calls] == (["low", "high"] if complete_remaining else ["low", "low", "low", "high"])
    receipt = json.loads(next(tmp_path.glob("invocations/*/receipt.json")).read_text())
    assert receipt["status"] == "completed"
    assert receipt["budget"]["limit_usd"] == 3
    assert receipt["budget"]["allow_overrun"] is complete_remaining
    if complete_remaining:
        assert receipt["budget"]["spent_usd"] == 1.8
        assert receipt["budget"]["completed"] == 900
        assert receipt["budget"]["stopped"] is False


def test_budget_extension_rearms_only_denials_and_archives_original(tmp_path):
    sys.path.insert(0, str(HERE))
    import run_dev3_v6 as launcher
    denied = dict(assignment_id="denied", status="failed", automatic_recovery_exhausted=True,
                  error_type="RubricProposerProviderError", automatic_attempt_count=1,
                  traceback="PermissionDeniedError: Budget relay stopped request: RuntimeError")
    records = [denied, {**denied, "assignment_id": "auth", "traceback": "invalid API key"},
               {**denied, "assignment_id": "done", "status": "completed"}]
    path = tmp_path / "study.json"
    path.write_text(json.dumps(dict(records=records)))
    original = path.read_bytes()
    invocation = tmp_path / "invocation"
    invocation.mkdir()
    assert launcher.rearm_budget_denials(path, invocation) == ["denied"]
    assert (invocation / "prior-budget-denial-study.json").read_bytes() == original
    updated = json.loads(path.read_text())["records"]
    assert updated[0]["automatic_recovery_exhausted"] is False
    assert updated[0]["automatic_attempt_count"] == 0
    assert updated[0]["status"] == "failed"
    assert updated[1:] == records[1:]
    assert launcher.rearm_budget_denials(path, invocation) == []
    assert (invocation / "prior-budget-denial-study.json").read_bytes() == original
