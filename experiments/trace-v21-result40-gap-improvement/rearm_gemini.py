"""Rearm the one reviewed response-free Gemini smoke-audit DNS failure."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921")
AUDIT = RUN / "audit/da-26-2/biomnibench-da-factorial-r10-b4d63d4e6dd8"
BASE = (
    ROOT
    / "experiments/trace-v21-execution-verified-provenance-result40"
    / "rearm_gemini_rate_limits.py"
)


def clean_commit() -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if dirty.strip():
        raise RuntimeError("Gemini recovery source must be a clean commit")
    return commit


def recovery_module():
    spec = importlib.util.spec_from_file_location("result40_gemini_rearm", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load reviewed Gemini recovery implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Gemini recovery must run through Slurm")
    commit = clean_commit()
    module = recovery_module()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    probe = AUDIT / "recovery-evidence" / f"probe-{stamp}"
    actions = module.semantic_actions(AUDIT, probe) + module.direct_actions(AUDIT, probe)
    expected = [{
        "kind": "direct_attempt",
        "stage": "direct_full_trajectory",
        "case_id": "revision-000006",
    }]
    observed = [
        {key: action.get(key) for key in expected[0]}
        for action in actions
    ]
    if observed != expected:
        raise RuntimeError(f"unexpected Gemini recovery scope: {observed}")
    receipt = RUN / f"gemini-dns-rearm-{stamp}.json"
    os.environ["RESULT40_EXPECTED_GEMINI_REARM"] = "1"
    os.environ["RESULT40_SOURCE_COMMIT"] = commit
    result = module.run(AUDIT, receipt)
    if result["provider_calls"] != 0 or result["request_semantics_changed"]:
        raise RuntimeError("Gemini recovery changed request semantics")
    print(json.dumps({
        "rearmed_items": result["rearmed_items"],
        "receipt": str(receipt),
        "source_commit": commit,
    }))


if __name__ == "__main__":
    main()
