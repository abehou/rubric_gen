"""Run the 30%/50% provenance/high-proposer dropout Dev3 on this Mac."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
BASE = ROOT / "experiments/trace-v21-execution-verified-high-allocation/run_local.py"
RUN_ROOT = ROOT / "runs/trace-v21-execution-verified-provenance-dropout-local-mac"
TRACE_VERSION = (
    "attack_defense_v2.1_execution_verified_proactive_provenance_dropout"
)
CONDITIONS = (
    "full-red-team-trace-execution-provenance-high-proposer-dropout-30",
    "full-red-team-trace-execution-provenance-high-proposer-dropout-50",
    "user-simulator-red-team-trace-execution-provenance-high-proposer-dropout-30",
    "user-simulator-red-team-trace-execution-provenance-high-proposer-dropout-50",
)


def _validate_saved_cases() -> dict[str, object]:
    receipt = RUN_ROOT / "saved-case-validation/validation.json"
    if receipt.is_symlink() or not receipt.is_file():
        raise RuntimeError("dropout saved-case validation is incomplete")
    value = json.loads(receipt.read_text(encoding="utf-8"))
    if (
        value.get("status") != "passed"
        or value.get("trace_version") != TRACE_VERSION
        or set(value.get("rates", [])) != {0.3, 0.5}
        or set(value.get("arms", [])) != {"full", "user_simulator"}
    ):
        raise RuntimeError("dropout saved-case validation did not pass")
    return {
        "path": str(receipt.resolve()),
        "sha256": sha256_file(receipt),
        "status": value["status"],
        "provider_calls": value["provider_calls"],
    }


def _runner():
    spec = importlib.util.spec_from_file_location(
        "provenance_dropout_parameterized_runner", BASE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the validated execution-verified runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BUNDLE = BUNDLE
    module.CONFIG = BUNDLE / "dev3.yaml"
    module.RUN_ROOT = RUN_ROOT
    module.CONDITIONS = CONDITIONS
    module.TRACE_VERSION = TRACE_VERSION
    module.RED_TEAM_REASONING_EFFORT = "low"
    module.PROPOSER_REASONING_BY_STAGE = {"diagnosis": "high"}
    module.RUN_KIND = "execution-provenance-high-proposer-dropout-local-dev3"
    module.COMPLETION_STAGE = "execution_provenance_dropout_dev3_complete"
    module.SAVED_CASE_VALIDATOR = _validate_saved_cases
    module.EXPECTED_ASSIGNMENTS = 36
    module.EXPECTED_DROPOUT_RATES = (0.3, 0.5)
    return module


if __name__ == "__main__":
    _runner().main()
