from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


BUNDLE = (
    Path(__file__).resolve().parents[1]
    / "experiments/trace-v21-result40-gap-improvement"
)


def load_module(name: str, filename: str):
    path = BUNDLE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(BUNDLE))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(BUNDLE))
    return module


def test_formal_audit_has_nine_missing_provider_task_scopes() -> None:
    module = load_module("gap_sol_opus_audit", "audit_sol_opus.py")
    scopes = module.planned_scopes()
    assert len(scopes) == 9
    assert (module.SMOKE_TASK, "sol") not in scopes
    assert (module.SMOKE_TASK, "opus") in scopes
    assert sum(provider == "sol" for _task, provider in scopes) == 4
    assert sum(provider == "opus" for _task, provider in scopes) == 5


def test_provider_scope_preserves_revision_identity_and_separates_outputs(
    monkeypatch,
) -> None:
    module = load_module("gap_sol_opus_scope", "audit_sol_opus.py")
    from rubric_gen.submission_revision.experiment import Experiment

    original = Experiment(
        Path("fixture.yaml"),
        {
            "experiment_id": "biomnibench-da-factorial-r10-fixture",
            "outcome_audit": {"models": list(module.HISTORICAL_PANEL)},
            "execution_audit_models": list(module.HISTORICAL_PANEL),
            "dag": {
                "revise": {"output_dir": "/data/study/fixture"},
                "paraphrase": {"output_dir": "/data/paraphrases"},
                "detect": {"output_dir": "/data/audit/history"},
            },
        },
    )
    monkeypatch.setattr(module, "load_experiment", lambda _path: original)
    sol = module.scoped_experiment("da-26-4", "sol")
    opus = module.scoped_experiment("da-26-4", "opus")
    assert sol.experiment_id == opus.experiment_id == original.experiment_id
    assert tuple(original.outcome_audit["models"]) == module.HISTORICAL_PANEL
    assert tuple(sol.outcome_audit["models"]) == ("gpt-5.6-sol",)
    assert tuple(opus.outcome_audit["models"]) == ("claude-opus-5",)
    assert sol.dag["detect"]["output_dir"] != opus.dag["detect"]["output_dir"]
    assert sol.dag["revise"] == original.dag["revise"]
    assert opus.dag["revise"] == original.dag["revise"]


def test_inventory_counts_only_saved_provider_material(tmp_path: Path) -> None:
    module = load_module("gap_audit_inventory", "audit_inventory.py")
    root = tmp_path / "audit"
    (root / "direct/case/model").mkdir(parents=True)
    (root / "direct/case/model/score.json").write_text("{}")
    (root / "rubric_score/records").mkdir(parents=True)
    (root / "rubric_score/records/a.json").write_text("{}")
    (root / "rubric_score/summary.json").write_text("{}")
    (root / "direct/case/model/request-001").mkdir()
    (root / "direct/case/model/request-001/attempt-001.json").write_text("{}")
    assert module.provider_material(root) == [
        "direct/case/model/request-001/attempt-001.json",
        "direct/case/model/score.json",
        "rubric_score/records/a.json",
    ]


def test_audit_launcher_uses_authorized_cpu_only_a6000_profile() -> None:
    text = (BUNDLE / "audit.sbatch").read_text()
    assert "#SBATCH --partition=general" in text
    assert "#SBATCH --qos=normal" in text
    assert "#SBATCH --gres=gpu:A6000:1" in text
    assert "#SBATCH --cpus-per-task=4" in text
    assert "#SBATCH --mem=32G" in text
    assert "#SBATCH --time=02:00:00" in text
    assert "--max-concurrency 60" in text
    inventory = (BUNDLE / "audit-inventory.sbatch").read_text()
    assert "#SBATCH --partition=general" in inventory
    assert "#SBATCH --gres=gpu:A6000:1" in inventory
    assert "#SBATCH --cpus-per-task=4" in inventory
    assert "#SBATCH --mem=32G" in inventory


def test_provider_audit_records_runtime_topology_and_sub_two_hour_eta() -> None:
    module = load_module("gap_sol_opus_runtime", "audit_sol_opus.py")
    assert module.MAX_CONCURRENCY == 60
    assert module.EXPECTED_WALL_TIME_MINUTES < 120
    text = (BUNDLE / "audit_sol_opus.py").read_text()
    assert '"outer_shard_workers": 1' in text
    assert '"per_shard_assignment_workers": args.max_concurrency' in text
    assert '"configured_aggregate_concurrency": runtime[' in text
    assert '"provider_request_cap_per_audit_owner": runtime[' in text
    assert '"internal_revision_fanout": 0' in text
    assert '"maximum_parallel_audit_owners": 3' in text
    assert '"maximum_total_request_workers_across_owners": 180' in text


def test_historical_sol_gemini_dispatch_is_disabled() -> None:
    text = (BUNDLE / "run.py").read_text()
    assert "historical Sol+Gemini audit dispatch is disabled" in text


def test_revision_resume_reuses_only_unchanged_sealed_tree_hashes(
    tmp_path: Path, monkeypatch,
) -> None:
    module = load_module("gap_revision_cli", "revision_cli.py")
    root = tmp_path / "red-team" / "checkpoint-0000" / "workspace"
    root.mkdir(parents=True)
    artifact = root / "artifact.bin"
    artifact.write_bytes(b"first")
    calls = []

    def fake_hash(path: Path) -> str:
        calls.append(Path(path))
        return f"digest-{len(calls)}"

    monkeypatch.setattr(module, "_ORIGINAL_TREE_SHA256", fake_hash)
    artifact.chmod(0o444)
    root.chmod(0o555)
    assert module.cached_tree_sha256(root) == "digest-1"
    assert module.cached_tree_sha256(root) == "digest-1"
    root.chmod(0o755)
    artifact.chmod(0o644)
    artifact.write_bytes(b"second-value")
    artifact.chmod(0o444)
    root.chmod(0o555)
    assert module.cached_tree_sha256(root) == "digest-2"
    assert calls == [root, root]


def test_revision_stage_uses_sealed_tree_resume_launcher() -> None:
    text = (BUNDLE / "run.py").read_text()
    assert 'str(BUNDLE / "revision_cli.py")' in text


def test_analysis_uses_sol_opus_and_excludes_historical_gemini() -> None:
    module = load_module("gap_sol_opus_analysis", "analyze.py")
    assert module.PANEL == ("gpt-5.6-sol", "claude-opus-5")
    assert module.HISTORICAL_PANEL == ("gpt-5.6-sol", "gemini-3.8-flash")
