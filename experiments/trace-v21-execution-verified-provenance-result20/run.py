"""Frozen Results20 revision and concurrent Sol+Opus audit entrypoint."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study_validation import validate_completed_revision

from prepare import BUNDLE, CONDITIONS, CONFIG, PANEL, ROOT, RUN, TASKS, sha

UV = Path("/home/aydanh/tools/uv/uv")
PYTHON = Path("/home/aydanh/repos/rubric_gen/.venv/bin/python")


def load_credentials() -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not values.get(key):
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(values[key])


def require_clean_source() -> str:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty.strip():
        raise RuntimeError("frozen Results20 worktree is not clean")
    return commit


def check_runtime(mode: str) -> dict:
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError("revision or audit-owner capacity changed")
    expected = {"openai": 60, "anthropic": 60}
    if runtime.get("audit_provider_concurrency") != expected:
        raise RuntimeError("Sol/Opus audit provider partitions changed")
    workers = 60 if mode == "execute" else 120
    return {**runtime, "stage_workers": workers}


def owner(mode: str, commit: str, experiment, runtime: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUN / "owners" / f"{mode}-{os.environ['SLURM_JOB_ID']}-{stamp}"
    path.mkdir(parents=True, exist_ok=False)
    write_json_atomic(path / "launch.json", {
        "mode": mode,
        "commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "started_at": stamp,
        "experiment_id": experiment.experiment_id,
        "config": str(CONFIG),
        "config_sha256": sha(CONFIG),
        "conditions": list(CONDITIONS),
        "tasks": list(TASKS),
        "cpus": int(os.environ["SLURM_CPUS_PER_TASK"]),
        "memory": "256G",
        "runtime": runtime,
        "internal_fanout": 4,
        "outputs": experiment.dag,
        "command": sys.argv,
    })
    return path


def progress_monitor(experiment, root: Path) -> None:
    expected = {assignment.assignment_id for assignment in experiment.execution_assignments}

    def monitor() -> None:
        while True:
            try:
                ledger = json.loads((Path(experiment.dag["revise"]["output_dir"]) / "study.json").read_text())
                rows = [row for row in ledger["records"] if row["assignment_id"] in expected]
                write_json_atomic(RUN / "status.json", {
                    "job_id": os.environ["SLURM_JOB_ID"],
                    "owner": str(root),
                    "time": datetime.now(timezone.utc).isoformat(),
                    "expected": len(expected),
                    "statuses": dict(Counter(row["status"] for row in rows)),
                })
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(30)

    threading.Thread(target=monitor, name="result20-progress", daemon=True).start()


def uv_stage(stage: str, workers: int) -> None:
    command = [
        str(UV), "run", "--no-sync", "rubric-gen", stage,
        "--experiment", str(CONFIG), "--max-concurrency", str(workers), "--resume",
    ]
    environment = dict(os.environ)
    environment.update({
        "PYTHONPATH": str(ROOT / "src"),
        "UV_PROJECT_ENVIRONMENT": str(PYTHON.parent.parent),
    })
    completed = subprocess.run(command, cwd=ROOT, env=environment)
    if completed.returncode:
        raise RuntimeError(f"{stage} exited with {completed.returncode}; saved work retained")


def complete_rows(experiment) -> list[dict]:
    study = Path(experiment.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text())
    rows = terminal_records(experiment, ledger)
    if len(rows) != 120 or any(row["status"] != "completed" for row in rows):
        raise RuntimeError("Results20 revision cohort is not 120/120 complete")
    seed = Path(experiment.dag["seed"]["output_dir"])
    paraphrase = Path(experiment.dag["paraphrase"]["output_dir"])
    assignments = {assignment.assignment_id: assignment for assignment in experiment.execution_assignments}
    for row in rows:
        validate_completed_revision(
            study / row["experiment_dir"], assignments[row["assignment_id"]],
            experiment, seed, paraphrase,
        )
    return rows


def install_reuse() -> list[str]:
    module_path = ROOT / "experiments/trace-attack-defense-v21/audit_reuse.py"
    spec = importlib.util.spec_from_file_location("result20_exact_audit_reuse", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact semantic judgment reuse")
    reuse = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reuse)
    baseline = json.loads((ROOT / "docs/reports/2026-09-09/baseline-freeze/results.json").read_text())
    sources = set()
    for path, digest in baseline["provenance"]["sources"].items():
        source = Path(path)
        if sha(source) != digest:
            raise RuntimeError(f"frozen comparison report changed: {source}")
        for row in json.loads(source.read_text())["rows"]:
            sources.add(Path(row["quality_path"]).parents[2])
    v2 = Path("/data/user_data/aydanh/rubric_gen/runs/result20-prompt-nofallback-v2-20260910")
    sources.update((v2 / "full-static", v2 / "user-simulator-static"))
    reuse.SOURCES = sorted(sources)
    reuse.install()
    return [str(path) for path in sorted(sources)]


def execute(experiment, path: Path) -> None:
    progress_monitor(experiment, path)
    uv_stage("revise", 60)
    rows = complete_rows(experiment)
    write_json_atomic(RUN / "revision-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "experiment_id": experiment.experiment_id,
        "assignment_count": len(rows),
        "commit": require_clean_source(),
    })


def audit(experiment, path: Path) -> None:
    complete_rows(experiment)
    sources = install_reuse()
    write_json_atomic(path / "audit-reuse-sources.json", {
        "sources": sources,
        "rule": "exact semantic request identity and native validation only",
    })
    uv_stage("detect", 120)
    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check
    study = Path(experiment.dag["revise"]["output_dir"])
    audit_root = Path(experiment.dag["detect"]["output_dir"])
    coverage = check(study, audit_root, expected_models=PANEL)
    if coverage["assignment_count"] != 120:
        raise RuntimeError("Results20 audit coverage mismatch")
    write_json_atomic(path / "coverage.json", coverage)
    write_json_atomic(RUN / "audit-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "experiment_id": experiment.experiment_id,
        "commit": require_clean_source(),
        "coverage": coverage,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("execute", "audit"))
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("Results20 production requires one 32-CPU Slurm allocation")
    commit = require_clean_source()
    runtime = check_runtime(args.mode)
    experiment = load_experiment(CONFIG)
    if len(experiment.execution_assignments) != 120:
        raise RuntimeError("frozen Results20 assignment count changed")
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError("frozen Results20 Sol+Opus panel changed")
    load_credentials()
    path = owner(args.mode, commit, experiment, runtime)
    (execute if args.mode == "execute" else audit)(experiment, path)
    write_json_atomic(path / "completed.json", {
        "success": True,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    main()
