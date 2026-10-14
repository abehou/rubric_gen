"""Run a Gemini-only extension over the two completed regression artifacts.

The completed revision study and the existing Sol/Opus audit remain read-only.
Adding an outcome auditor does not change the saved solver trajectories, so this
private runner keeps their recorded experiment identity while writing the new
Gemini judgments to a separate audit directory.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import audit_output_owner
from rubric_gen.submission_revision.commands import _run_detect_owned
from rubric_gen.submission_revision.experiment import Experiment, load_experiment


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "experiments/trace-v21-complete-public-regression"
SOURCE_CONFIG = BUNDLE / "configs/da-26-4-rep002.yaml"
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921"
)
GEMINI = "gemini-3.8-flash"


def gemini_scope(original: Experiment, output_dir: Path) -> Experiment:
    payload = deepcopy(original.payload)
    declared = list(payload["outcome_audit"]["models"])
    if GEMINI not in declared:
        payload["outcome_audit"]["models"] = [*declared, GEMINI]
    payload["execution_audit_models"] = [GEMINI]
    payload["dag"]["detect"]["output_dir"] = str(output_dir)
    scoped = replace(original, payload=payload)
    if scoped.experiment_id != original.experiment_id:
        raise RuntimeError("Gemini audit extension changed the revision identity")
    if scoped.assignments != original.assignments:
        raise RuntimeError("Gemini audit extension changed assignment membership")
    if tuple(scoped.outcome_audit["models"]) != (GEMINI,):
        raise RuntimeError("Gemini audit extension selected another provider")
    return scoped


def main() -> int:
    original = load_experiment(SOURCE_CONFIG)
    study_dir = Path(original.dag["revise"]["output_dir"])
    paraphrase_dir = Path(original.dag["paraphrase"]["output_dir"])
    output_dir = RUN / "audit-gemini-authenticated" / original.experiment_id
    scoped = gemini_scope(original, output_dir)
    workers = 12
    receipt = {
        "kind": "complete-public-gemini-audit-extension",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_experiment_id": original.experiment_id,
        "source_config": str(SOURCE_CONFIG),
        "study_dir": str(study_dir),
        "output_dir": str(output_dir),
        "models": [GEMINI],
        "reused_models": ["gpt-5.6-sol"],
        "excluded_unavailable_models": ["claude-opus-5"],
        "assignment_ids": [
            assignment.assignment_id
            for assignment in scoped.execution_assignments
        ],
        "max_concurrency": workers,
        "resume": True,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_dir / "launch.json", receipt)
    args = argparse.Namespace(max_concurrency=workers, resume=True)
    with audit_output_owner(output_dir):
        exit_code = _run_detect_owned(
            args,
            scoped,
            study_dir,
            paraphrase_dir,
            output_dir,
        )
    completion = {
        **receipt,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "exit_code": int(exit_code),
    }
    write_json_atomic(output_dir / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
