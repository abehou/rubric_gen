"""Rearm only saved Gemini 429/503 failures for the feedback Result20 audit."""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic

from prepare import RUN


EXPERIMENT_ID = "biomnibench-da-factorial-r10-2e389d4e31bb"
ROOT = RUN / "audit-gemini" / EXPERIMENT_ID
BASE = (
    Path(__file__).parents[1]
    / "trace-v21-execution-verified-provenance-result40"
    / "rearm_gemini_rate_limits.py"
)


def _base_module():
    spec = importlib.util.spec_from_file_location("result40_gemini_rearm", BASE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the reviewed Gemini rearm implementation")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Gemini audit recovery must run through Slurm")
    module = _base_module()
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise RuntimeError(f"Gemini audit root is unavailable: {ROOT}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ROOT / "recovery-evidence" / f"gemini-rate-limit-rearm-{stamp}"
    actions = module.semantic_actions(ROOT, archive) + module.direct_actions(ROOT, archive)
    if not actions:
        raise RuntimeError("no supported Gemini operational failures require rearm")
    for action in actions:
        source = Path(str(action["source"]))
        destination = Path(str(action["archive"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    receipt = RUN / f"gemini-rate-limit-rearm-{stamp}.json"
    result = {
        "kind": "result20-feedback-gemini-rate-limit-rearm",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.environ.get("RESULT20_FEEDBACK_SOURCE_COMMIT"),
        "provider_calls": 0,
        "request_semantics_changed": False,
        "model": module.MODEL,
        "gemini_executor_workers_after_rearm": 12,
        "actions": actions,
        "rearmed_items": len(actions),
    }
    write_json_atomic(receipt, result)
    print(json.dumps({"rearmed_items": len(actions), "receipt": str(receipt)}))


if __name__ == "__main__":
    main()
