"""Recover only the one incomplete promoted-old20 Gemini audit scope."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os

from rubric_gen.artifacts.serialization import write_json_atomic

from audit_scope import GEMINI_PANEL, old20_gemini_scopes
from make_configs import RUN
from run import audit_stage, credentials


SCOPE = "old20-current-gemini"


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Gemini audit recovery must run through Slurm")
    scopes = dict(old20_gemini_scopes())
    if set(scopes) != {
        "old20-static-full-gemini",
        "old20-static-user-gemini",
        SCOPE,
    }:
        raise RuntimeError(f"old20 Gemini scope changed: {sorted(scopes)}")
    experiment = scopes[SCOPE]
    if tuple(experiment.outcome_audit["models"]) != GEMINI_PANEL:
        raise RuntimeError("old20 current recovery panel changed")
    credentials("audit")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    owner = RUN / "owners" / f"audit-old20-current-gemini-{os.environ['SLURM_JOB_ID']}-{stamp}"
    owner.mkdir(parents=True, exist_ok=False)
    result = audit_stage(SCOPE, experiment, 1, owner / "detect.log")
    receipt = {
        "kind": "results40-old20-current-gemini-missing-only",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.environ.get("RESULT40_SOURCE_COMMIT"),
        "job_id": os.environ["SLURM_JOB_ID"],
        "provider": "google",
        "model": GEMINI_PANEL[0],
        "workers": 1,
        "scope": result,
    }
    write_json_atomic(owner / "completed.json", receipt)
    print(json.dumps(receipt), flush=True)
    if result["exit_code"] != 0:
        raise RuntimeError(f"old20 current Gemini recovery failed: {result}")


if __name__ == "__main__":
    main()
