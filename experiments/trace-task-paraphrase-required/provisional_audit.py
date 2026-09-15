"""Run the authoritative Sol+Opus audit for the completed scoped views.

The caller mounts NAS1 mirrors at the historical input paths in a private mount
namespace.  This keeps recorded request identities unchanged while ensuring
the audit never reads the stalled NAS8 input export.  Only the selected 16
completed records are presented through the scoped ledgers.
"""
from __future__ import annotations

import argparse
import importlib.util
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
from rubric_gen.submission_revision.source_resolution import resolve_study_sources
from rubric_gen.submission_revision.evaluation.direct import DirectDetectionConfig, prepare_direct_detection
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner, RubricFreeScoreRunner


ROOT = Path(__file__).resolve().parents[2]
BASE = Path("/home/aydanh/runs/trace-task-paraphrase-required-20260914")
PROVISIONAL = BASE / "provisional-audit"
AUDIT_ROOT = Path(os.environ.get("TRACE_PROVISIONAL_AUDIT_ROOT", str(PROVISIONAL / "audit")))
TASKS = ("da-3-4", "da-11-1", "da-18-1")
PANEL = ("gpt-5.6-sol", "claude-opus-5")
REUSE_SOURCES = (
    Path("/home/aydanh/repos/rubric_gen/runs/autonomous-dev3-20260907/"
         "isolation-cachefix-smoke/audit/biomnibench-da-factorial-r3-3686c8965c2e"),
    Path("/home/aydanh/repos/rubric_gen/runs/autonomous-dev3-20260907/"
         "baseline-da11/audit/biomnibench-da-factorial-r3-ac929d893d67"),
)


def _identity_mismatches(view: Path, exp) -> dict[str, object]:
    """Return source-study identity fields that would reject native resolution."""
    ledger = json.loads((view / "study.json").read_text())
    root = view.resolve()
    expected = {
        "kind": "rubric-gen-randomized-revision-study",
        "experiment_id": exp.experiment_id,
        "experiment_path": str(exp.path),
        "seed_run_dir": str(Path(exp.dag["seed"]["output_dir"]).resolve()),
        "paraphrase_run_dir": str(Path(exp.dag["paraphrase"]["output_dir"]).resolve()),
        "pretreatment_rubric_root": str(root / "pretreatment-rubrics"),
    }
    return {
        key: {"ledger": ledger.get(key), "expected": value}
        for key, value in expected.items()
        if ledger.get(key) != value
    }


def configure_credentials() -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not values.get(key):
            raise RuntimeError(f"configured {key} is absent")
        os.environ[key] = str(values[key])


def install_exact_reuse() -> None:
    """Install the existing exact semantic reuse adapter with absolute sources."""
    adapter_path = ROOT / "experiments/trace-attack-defense-v21/audit_reuse.py"
    spec = importlib.util.spec_from_file_location("trace_v21_audit_reuse", adapter_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load exact reuse adapter: {adapter_path}")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.SOURCES = list(REUSE_SOURCES)
    adapter.install()


def run_task(task: str) -> dict[str, object]:
    config_path = ROOT / "experiments/trace-task-paraphrase-required/canonical" / f"{task}.yaml"
    view = PROVISIONAL / "views" / task
    output = AUDIT_ROOT / task
    exp = load_experiment(config_path)
    if tuple(exp.outcome_audit["models"]) != PANEL:
        raise RuntimeError(f"unexpected audit panel in {config_path}")
    ledger = json.loads((view / "study.json").read_text())
    mismatches = _identity_mismatches(view, exp)
    if mismatches:
        raise RuntimeError(f"source identity mismatch diagnostics for {task}: {json.dumps(mismatches, sort_keys=True)}")
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


def preflight_task(task: str) -> dict[str, object]:
    """Load and prepare every native audit stage without executing a call."""
    config_path = ROOT / "experiments/trace-task-paraphrase-required/canonical" / f"{task}.yaml"
    view = PROVISIONAL / "views" / task
    output = AUDIT_ROOT / task
    exp = load_experiment(config_path)
    exp.dag["detect"]["output_dir"] = str(output)
    mismatches = _identity_mismatches(view, exp)
    if mismatches:
        raise RuntimeError(f"source identity mismatch diagnostics for {task}: {json.dumps(mismatches, sort_keys=True)}")
    sources = resolve_study_sources(view, exp)
    common = dict(experiment=exp, study_dir=view,
                  paraphrase_dir=Path(str(exp.dag["paraphrase"]["output_dir"])),
                  max_concurrency=8, resume=True)
    rubric_config = EvaluationConfig(output_dir=output / "rubric_score", **common)
    free_config = EvaluationConfig(output_dir=output, **common)
    targets = load_evaluation_targets(rubric_config, sources)
    direct = [prepare_direct_detection(DirectDetectionConfig(
        experiment=exp, study_dir=view, output_dir=output / f"direct_{window.value}",
        max_concurrency=8, resume=True, window=window), sources, {})
        for window in RevisionDetectionWindow]
    rubric_runner = RubricScoreRunner(rubric_config, targets)
    free_runner = RubricFreeScoreRunner(free_config, targets)
    rubric_runner.preflight()
    free_runner.preflight()
    reused = [rubric_runner.prepare_resume(), free_runner.prepare_resume()]
    reused.extend(runner.prepare_resume() for runner in direct)
    return {"task": task, "assignments": len(targets), "rubric_reused": reused[0],
            "free_reused": reused[1], "direct_reused": reused[2:],
            "output": str(output)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=TASKS, action="append")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("provisional audit must run on Slurm")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError(f"unexpected shared capacity policy: {runtime}")
    tasks = tuple(args.task or TASKS)
    if args.preflight_only:
        rows = [preflight_task(task) for task in tasks]
        receipt = {"kind": "provisional-16-assignment-audit-preflight",
                   "candidate": "attack_defense_v2.1_task_paraphrase_required",
                   "job": os.environ["SLURM_JOB_ID"], "tasks": rows,
                   "provider_calls": 0}
        write_json_atomic(PROVISIONAL / "audit-preflight.json", receipt)
        print(json.dumps({"stage": "provisional_audit_preflight_complete", "tasks": list(tasks), "assignments": sum(r["assignments"] for r in rows)}), flush=True)
        return
    configure_credentials()
    install_exact_reuse()
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
