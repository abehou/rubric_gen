"""Run the proactive execution-verified, Luna-high-proposer Dev3 on this Mac."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
BASE = ROOT / "experiments/trace-v21-execution-verified-high-allocation/run_local.py"
RUN_ROOT = (
    ROOT / "runs/trace-v21-execution-verified-proactive-high-proposer-local-mac"
)


def _validate_saved_cases() -> dict[str, object]:
    receipt = RUN_ROOT / "saved-case-behavior-approved/validation.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise RuntimeError("proactive saved-case validation is incomplete")
    value = json.loads(receipt.read_text(encoding="utf-8"))
    expected = {
        "user-da-11-1-rep-001",
        "user-da-11-1-rep-002",
        "user-da-11-1-rep-003",
        "full-da-11-1-rep-001",
    }
    if (
        value.get("trace_version")
        != "attack_defense_v2.1_execution_verified_proactive"
        or value.get("status") != "passed"
        or set(value.get("passed_cases", [])) != expected
    ):
        raise RuntimeError("proactive saved-case behavior checks did not all pass")
    return {
        "path": str(receipt.resolve()),
        "sha256": sha256_file(receipt),
        "status": value["status"],
        "estimated_cost_usd": value.get("estimated_cost_usd"),
    }


def _runner():
    spec = importlib.util.spec_from_file_location(
        "execution_verified_parameterized_runner", BASE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the validated execution-verified runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BUNDLE = BUNDLE
    module.CONFIG = BUNDLE / "dev3.yaml"
    module.RUN_ROOT = RUN_ROOT
    module.CONDITIONS = (
        "full-red-team-trace-execution-verified-proactive-high-proposer",
        "user-simulator-red-team-trace-execution-verified-proactive-high-proposer",
    )
    module.TRACE_VERSION = (
        "attack_defense_v2.1_execution_verified_proactive"
    )
    module.RED_TEAM_REASONING_EFFORT = "low"
    module.PROPOSER_REASONING_BY_STAGE = {"diagnosis": "high"}
    module.RUN_KIND = (
        "execution-verified-proactive-high-proposer-local-dev3"
    )
    module.COMPLETION_STAGE = (
        "execution_verified_proactive_high_proposer_dev3_complete"
    )
    module.SAVED_CASE_VALIDATOR = _validate_saved_cases
    return module


if __name__ == "__main__":
    _runner().main()
