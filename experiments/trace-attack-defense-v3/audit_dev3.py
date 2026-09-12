"""Run the frozen Sol+Opus development audit for one saved dev3 flavor."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.commands import run_detect
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.execution_scope import terminal_records


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911")
TASKS = ("da-3-4", "da-11-1", "da-18-1")
STRESS_TASKS = ("da-15-1", "da-13-6", "da-18-5")
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def install_reuse() -> None:
    source = ROOT / "experiments/trace-attack-defense-v21/audit_reuse.py"
    spec = importlib.util.spec_from_file_location("trace_v21_audit_reuse", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import the reviewed audit-reuse adapter")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("flavor", choices=("control-v21-compatible", "v21-control", "v3-candidate", "v31-candidate"))
    parser.add_argument("cohort", choices=("canonical", "stress"))
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("dev3 audit requires a 32-CPU Slurm allocation")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError("shared capacity policy differs")
    credentials = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not credentials.get(key):
            raise RuntimeError(f"configured {key} absent")
        os.environ[key] = str(credentials[key])
    install_reuse()
    tasks = TASKS if args.cohort == "canonical" else STRESS_TASKS
    if args.flavor == "control-v21-compatible":
        config_dir = BUNDLE / "control-v21-compatible"
    elif args.flavor == "v31-candidate":
        config_dir = BUNDLE / ("canonical-v31" if args.cohort == "canonical" else "stress-v31")
    else:
        config_dir = BUNDLE / "stress"
    rows = []
    for task in tasks:
        if args.flavor == "control-v21-compatible" or args.cohort == "canonical":
            config_path = config_dir / f"{task}.yaml"
        else:
            config_path = config_dir / f"{args.flavor}-{task}.yaml"
        exp = load_experiment(config_path)
        if tuple(exp.outcome_audit["models"][:2]) != PANEL:
            raise RuntimeError(f"unexpected configured panel in {config_path}")
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        completed = terminal_records(exp, ledger)
        if len(completed) != 3 or any(r["status"] != "completed" for r in completed):
            raise RuntimeError(f"audit requires 3 completed assignments: {config_path}")
        args_detect = SimpleNamespace(experiment=str(config_path), study_dir=None, max_concurrency=32, resume=True)
        code = run_detect(args_detect)
        if code:
            raise RuntimeError(f"native audit returned {code} for {config_path}")
        audit = Path(exp.dag["detect"]["output_dir"])
        rows.append({
            "task": task,
            "experiment": str(config_path),
            "experiment_id": exp.experiment_id,
            "study": str(study),
            "audit": str(audit),
            "config_sha256": sha256_file(config_path),
        })
    receipt = {
        "kind": "dev3_sol_opus_audit",
        "job": os.environ["SLURM_JOB_ID"],
        "flavor": args.flavor,
        "cohort": args.cohort,
        "panel": list(PANEL),
        "tasks": rows,
        "gemini": "not configured for this authoritative development audit",
        "reuse_adapter": str(ROOT / "experiments/trace-attack-defense-v21/audit_reuse.py"),
    }
    write_json_atomic(BUNDLE / f"audit-{args.cohort}-{args.flavor}.json", receipt)
    print(json.dumps({"stage": "dev3_audit_complete", "flavor": args.flavor, "cohort": args.cohort, "tasks": len(rows)}), flush=True)


if __name__ == "__main__":
    main()
