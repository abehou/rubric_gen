"""Provider-free checks for the BioMNIBench Result50 extension bundle."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

from rubric_gen.submission_revision.paraphrase_protocol import (
    NEUTRAL_PARAPHRASE_INSTRUCTIONS,
    PARAPHRASE_INSTRUCTIONS,
)


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "experiments/trace-v21-execution-verified-provenance-result50"
RESULT40 = ROOT / "experiments/trace-v21-execution-verified-provenance-result40"


def test_result50_is_exact_full_dataset_complement_of_result40():
    extension = json.loads((BUNDLE / "membership.json").read_text())
    result40 = json.loads((RESULT40 / "membership.json").read_text())
    original20 = yaml.safe_load(
        (
            ROOT
            / "experiments/trace-v21-execution-verified-provenance-result20/result20.yaml"
        ).read_text()
    )["tasks"]
    upstream = json.loads(
        (ROOT / "experiments/biomnibench-v21-to45/queue6/membership.json").read_text()
    )
    result40_tasks = set(original20) | set(result40["new20"])
    added10 = extension["added10"]

    assert len(result40_tasks) == 40
    assert len(added10) == len(set(added10)) == 10
    assert not result40_tasks.intersection(added10)
    assert result40_tasks | set(added10) == (
        set(upstream["results45"])
        | set(upstream["protected_dev3"])
        | {"da-20-3", "da-5-3"}
    )
    assert extension["new_assignments"] == 120
    assert extension["result50_task_count"] == 50


def test_result50_keeps_result40_models_recipe_and_rigorous_heldouts():
    runtime = json.loads((BUNDLE / "runtime.json").read_text())
    membership = json.loads((BUNDLE / "membership.json").read_text())
    make_configs_path = BUNDLE / "make_configs.py"
    spec = importlib.util.spec_from_file_location("result50_make_configs_test", make_configs_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.CANDIDATE == (
        "attack_defense_v2.1_execution_verified_proactive_provenance"
    )
    assert module.PANEL == ("gpt-5.6-sol", "claude-opus-5")
    assert module.TASKS == tuple(membership["added10"])
    assert module.RESULT45_TASKS == module.TASKS[:5]
    assert module.GENERATED_INPUT_TASKS == module.TASKS[5:]
    assert runtime["aggregate_concurrency"] == 60
    assert runtime["audit_provider_concurrency"] == {
        "openai": 60,
        "anthropic": 60,
    }
    assert "prefer the stricter" in PARAPHRASE_INSTRUCTIONS
    assert "strengthen, clarify, or repair" in NEUTRAL_PARAPHRASE_INSTRUCTIONS


def test_result50_slurm_chain_uses_recorded_babel_capacity():
    setup = (BUNDLE / "setup.sbatch").read_text()
    revise = (BUNDLE / "revise.sbatch").read_text()
    audit = (BUNDLE / "audit.sbatch").read_text()

    assert "#SBATCH --cpus-per-task=8" in setup
    assert "#SBATCH --mem=64G" in setup
    for script in (revise, audit):
        assert "#SBATCH --cpus-per-task=32" in script
        assert "#SBATCH --mem=256G" in script
        assert "export RESULT40_EXPECTED_CPUS=32" in script
