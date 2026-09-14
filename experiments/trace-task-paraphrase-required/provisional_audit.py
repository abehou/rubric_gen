"""Run the authoritative Sol+Opus audit for the completed scoped views.

The caller mounts NAS1 mirrors at the historical input paths in a private mount
namespace.  This keeps recorded request identities unchanged while ensuring
the audit never reads the stalled NAS8 input export.  Only the selected 16
completed records are presented through the scoped ledgers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import audit_output_owner
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.commands import _run_detect_owned
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.execution_scope import terminal_records


ROOT = Path(__file__).resolve().parents[2]
BASE = Path("/home/aydanh/runs/trace-task-paraphrase-required-20260914")
PROVISIONAL = BASE / "provisional-audit"
TASKS = ("da-3-4", "da-11-1", "da-18-1")
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def configure_credentials() -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not values.get(key):
            raise RuntimeError(f"configured {key} is absent")
        os.environ[key] = str(values[key])


def run_task(task: str) -> dict[str, object]:
    config_path = ROOT / "experiments/trace-task-paraphrase-required/canonical" / f"{task}.yaml"
    view = PROVISIONAL / "views" / task
    output = PROVISIONAL / "audit" / task
    exp = load_experiment(config_path)
    if tuple(exp.outcome_audit["models"]) != PANEL:
        raise RuntimeError(f"unexpected audit panel in {config_path}")
    ledger = json.loads((view / "study.json").read_text())
    completed = terminal_records(exp, ledger)
    expected = 6 if task != "da-11-1" else 4
    if len(completed) != expected or any(r["status"] != "completed" for r in completed):
        raise RuntimeError(f"scoped view is not terminal for {task}")
    # The experiment identity and all source paths remain those recorded in the
    # original config/ledger.  Only the destination is redirected to this
    # separate, persistent provisional audit root.
    exp.dag["detect"]["output_dir"] = str(output)
    args = SimpleNamespace(max_concurrency=8, resume=True)
    output.mkdir(parents=True, exist_ok=True)
    with audit_output_owner(output):
        code = _run_detect_owned(
            args,
            exp,
            view,
            Path(str(exp.dag["paraphrase"]["output_dir"])),
            output,
        )
    if code:
        raise RuntimeError(f"native audit returned {code} for {task}")
    return {
        "task": task,
        "config": str(config_path),
        "config_sha256": sha256_file(config_path),
        "view": str(view),
        "audit": str(output),
        "experiment_id": exp.experiment_id,
        "assignments": len(completed),
        "models": list(PANEL),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=TASKS, action="append")
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("provisional audit must run on Slurm")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError(f"unexpected shared capacity policy: {runtime}")
    configure_credentials()
    tasks = tuple(args.task or TASKS)
    receipt = {
        "kind": "provisional-16-assignment-sol-opus-audit",
        "candidate": "attack_defense_v2.1_task_paraphrase_required",
        "job": os.environ["SLURM_JOB_ID"],
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "panel": list(PANEL),
        "tasks": [],
        "provider_calls": "missing-only native stages; exact reusable records preserved",
    }
    for task in tasks:
        row = run_task(task)
        receipt["tasks"].append(row)
        write_json_atomic(PROVISIONAL / f"audit-{task}.json", receipt)
    write_json_atomic(PROVISIONAL / "audit-receipt.json", receipt)
    print(json.dumps({"stage": "provisional_audit_complete", "tasks": list(tasks), "assignments": sum(r["assignments"] for r in receipt["tasks"])}), flush=True)


if __name__ == "__main__":
    main()
