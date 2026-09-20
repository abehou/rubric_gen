"""Frozen Semi/Score-only Results20 revision and three-auditor execution."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import replace
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
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources
from rubric_gen.submission_revision.study_validation import validate_completed_revision

from prepare import BUNDLE, CONDITIONS, CONFIG, PANEL, ROOT, RUN, TASKS, sha

UV = Path("/home/aydanh/tools/uv/uv")
PYTHON = Path("/home/aydanh/repos/rubric_gen/.venv/bin/python")
SOL_OPUS = ("gpt-5.6-sol", "claude-opus-5")
GEMINI = ("gemini-3.8-flash",)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def credentials(mode: str) -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    keys = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
    if mode == "audit":
        keys = (*keys, "GEMINI_API_KEY")
    for key in keys:
        if not values.get(key):
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(values[key])


def clean_commit() -> str:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty.strip():
        raise RuntimeError("frozen Results20 feedback worktree is not clean")
    return commit


def runtime(mode: str) -> dict:
    value = policy()
    if value["aggregate_concurrency"] != 60 or value["audit_studies"] != 3:
        raise RuntimeError("Results20 feedback capacity policy changed")
    expected = {"openai": 60, "anthropic": 60, "google": 60}
    if value.get("audit_provider_concurrency") != expected:
        raise RuntimeError("Results20 feedback audit partitions changed")
    return {**value, "stage_workers": 60 if mode == "execute" else 120}


def owner(mode: str, commit: str, capacity: dict, experiment) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = RUN / "owners" / f"{mode}-{os.environ['SLURM_JOB_ID']}-{stamp}"
    root.mkdir(parents=True, exist_ok=False)
    write_json_atomic(root / "launch.json", {
        "mode": mode,
        "source_commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "started_at": stamp,
        "experiment_id": experiment.experiment_id,
        "config": str(CONFIG),
        "config_sha256": sha(CONFIG),
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignment_count": 240,
        "cpus": int(os.environ["SLURM_CPUS_PER_TASK"]),
        "memory_mb": int(os.environ["SLURM_MEM_PER_NODE"]),
        "runtime": capacity,
        "internal_fanout": 4,
        "command": sys.argv,
    })
    return root


def progress_monitor(experiment) -> None:
    expected = {assignment.assignment_id for assignment in experiment.execution_assignments}

    def monitor() -> None:
        while True:
            try:
                ledger = json.loads((Path(experiment.dag["revise"]["output_dir"]) / "study.json").read_text())
                rows = [row for row in ledger["records"] if row["assignment_id"] in expected]
                write_json_atomic(RUN / "status.json", {
                    "job_id": os.environ["SLURM_JOB_ID"],
                    "time": now(),
                    "expected": len(expected),
                    "statuses": dict(Counter(row["status"] for row in rows)),
                })
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(30)

    threading.Thread(target=monitor, name="result20-feedback-progress", daemon=True).start()


def environment() -> dict:
    result = dict(os.environ)
    result.update({
        "PYTHONPATH": str(ROOT / "src"),
        "UV_PROJECT_ENVIRONMENT": str(PYTHON.parent.parent),
    })
    return result


def uv_revise() -> None:
    command = [
        str(UV), "run", "--no-sync", "rubric-gen", "revise",
        "--experiment", str(CONFIG), "--max-concurrency", "60", "--resume",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=environment())
    if completed.returncode:
        raise RuntimeError(f"revise exited with {completed.returncode}; saved work retained")


def complete_rows(experiment, *, full_validation: bool) -> list[dict]:
    study = Path(experiment.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text())
    rows = terminal_records(experiment, ledger)
    if len(rows) != 240 or any(row["status"] != "completed" for row in rows):
        raise RuntimeError("Results20 feedback revisions are not 240/240 complete")
    assignments = {assignment.assignment_id: assignment for assignment in experiment.execution_assignments}
    if full_validation:
        seed = Path(experiment.dag["seed"]["output_dir"])
        paraphrase = Path(experiment.dag["paraphrase"]["output_dir"])
        for row in rows:
            validate_completed_revision(
                study / row["experiment_dir"], assignments[row["assignment_id"]],
                experiment, seed, paraphrase,
            )
    else:
        sources = resolve_study_sources(study, experiment)
        targets = load_evaluation_targets(EvaluationConfig(
            experiment=experiment,
            study_dir=study,
            paraphrase_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
            output_dir=Path(experiment.dag["detect"]["output_dir"]),
            max_concurrency=6,
            resume=True,
        ), sources)
        if len(targets) != 240 or {target.assignment_id for target in targets} != set(assignments):
            raise RuntimeError("Results20 feedback audit targets differ from completed revisions")
    return rows


def validate_matched_inputs(experiment, rows: list[dict]) -> None:
    study = Path(experiment.dag["revise"]["output_dir"])
    assignments = {assignment.assignment_id: assignment for assignment in experiment.execution_assignments}
    hashes: dict[tuple[str, int], set[str]] = {}
    conditions = set()
    for row in rows:
        assignment = assignments[row["assignment_id"]]
        manifest = json.loads((study / row["experiment_dir"] / "manifest.json").read_text())
        hashes.setdefault((assignment.task_id, assignment.replicate), set()).add(manifest["seed_sha256"])
        conditions.add(assignment.condition_id)
    if conditions != set(CONDITIONS) or any(len(value) != 1 for value in hashes.values()):
        raise RuntimeError("four feedback conditions do not share matched starting seeds")


def scoped_experiment(experiment, models: tuple[str, ...], output_dir: Path):
    payload = deepcopy(experiment.payload)
    payload["execution_audit_models"] = list(models)
    payload["dag"]["detect"]["output_dir"] = str(output_dir)
    scoped = replace(experiment, payload=payload)
    if scoped.experiment_id != experiment.experiment_id:
        raise RuntimeError("audit scope changed revision experiment identity")
    if tuple(scoped.outcome_audit["models"]) != models:
        raise RuntimeError("audit scope did not select requested panel")
    return scoped


def install_reuse() -> list[str]:
    module_path = ROOT / "experiments/trace-attack-defense-v21/audit_reuse.py"
    spec = importlib.util.spec_from_file_location("result20_feedback_exact_reuse", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load exact semantic judgment reuse")
    reuse = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reuse)
    candidates = (
        Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/audit/biomnibench-da-factorial-r10-682343156c5d"),
        Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/audit-gemini/old20/current/biomnibench-da-factorial-r10-682343156c5d"),
        Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/audit-gemini/old20/static-full/biomnibench-da-factorial-r10-bfbdd0f9833c"),
        Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/audit-gemini/old20/static-user/biomnibench-da-factorial-r10-f0203f5d69f3"),
    )
    sources = [path for path in candidates if path.is_dir()]
    reuse.SOURCES = sources
    reuse.install()
    return [str(path) for path in sources]


def audit_stage(name: str, experiment, workers: int, log: Path) -> dict:
    from rubric_gen.runtime.audit_execution import audit_output_owner
    from rubric_gen.submission_revision.commands import _run_detect_owned

    output_dir = Path(experiment.dag["detect"]["output_dir"])
    args = argparse.Namespace(max_concurrency=workers, resume=True)
    started = now()
    exit_code = 1
    error = None
    try:
        with log.open("a") as output, redirect_stdout(output), redirect_stderr(output):
            with audit_output_owner(output_dir):
                exit_code = _run_detect_owned(
                    args, experiment,
                    Path(experiment.dag["revise"]["output_dir"]),
                    Path(experiment.dag["paraphrase"]["output_dir"]),
                    output_dir,
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    return {
        "scope": name,
        "models": list(experiment.outcome_audit["models"]),
        "workers": workers,
        "output_dir": str(output_dir),
        "exit_code": int(exit_code),
        "error": error,
        "started_at": started,
        "finished_at": now(),
    }


def execute(experiment) -> None:
    progress_monitor(experiment)
    uv_revise()
    rows = complete_rows(experiment, full_validation=True)
    validate_matched_inputs(experiment, rows)
    write_json_atomic(RUN / "revision-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "experiment_id": experiment.experiment_id,
        "config_sha256": sha(CONFIG),
        "assignment_count": len(rows),
        "conditions": list(CONDITIONS),
        "finished_at": now(),
    })


def check_revision_receipt(experiment) -> None:
    receipt = json.loads((RUN / "revision-completion.json").read_text())
    if (
        receipt.get("success") is not True
        or receipt.get("experiment_id") != experiment.experiment_id
        or receipt.get("config_sha256") != sha(CONFIG)
        or receipt.get("assignment_count") != 240
        or tuple(receipt.get("conditions", ())) != CONDITIONS
    ):
        raise RuntimeError("validated Results20 feedback revision receipt differs")
    rows = complete_rows(experiment, full_validation=False)
    validate_matched_inputs(experiment, rows)


def audit(experiment, path: Path) -> None:
    check_revision_receipt(experiment)
    sources = install_reuse()
    write_json_atomic(path / "audit-reuse-sources.json", {
        "sources": sources,
        "rule": "exact semantic request identity and native validation only",
    })
    scopes = (
        ("sol-opus", scoped_experiment(experiment, SOL_OPUS, Path(experiment.dag["detect"]["output_dir"])), 120),
        ("gemini", scoped_experiment(experiment, GEMINI, RUN / "audit-gemini" / experiment.experiment_id), 1),
    )
    status = {"job_id": os.environ["SLURM_JOB_ID"], "started_at": now(), "scopes": {}}
    write_json_atomic(RUN / "audit-status.json", status)
    for name, scoped, workers in scopes:
        result = audit_stage(name, scoped, workers, path / f"detect-{name}.log")
        status["scopes"][name] = result
        write_json_atomic(RUN / "audit-status.json", status)
        print(json.dumps(result), flush=True)
        if result["exit_code"]:
            raise RuntimeError(f"Results20 feedback {name} audit incomplete; saved judgments retained")

    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check
    coverage = {}
    for name, scoped, _workers in scopes:
        value = check(
            Path(scoped.dag["revise"]["output_dir"]),
            Path(scoped.dag["detect"]["output_dir"]),
            expected_models=tuple(scoped.outcome_audit["models"]),
        )
        if value.get("assignment_count") != 240:
            raise RuntimeError(f"Results20 feedback {name} audit coverage mismatch")
        coverage[name] = value
    status["complete"] = True
    status["finished_at"] = now()
    write_json_atomic(RUN / "audit-status.json", status)
    write_json_atomic(RUN / "audit-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "experiment_id": experiment.experiment_id,
        "config_sha256": sha(CONFIG),
        "panels": {"sol_opus": list(SOL_OPUS), "gemini": list(GEMINI), "combined": list(PANEL)},
        "coverage": coverage,
        "finished_at": now(),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("execute", "audit"))
    args = parser.parse_args()
    expected_cpus = int(os.environ.get("RESULT20_FEEDBACK_EXPECTED_CPUS", "32"))
    if (
        not os.environ.get("SLURM_JOB_ID")
        or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != expected_cpus
    ):
        raise RuntimeError(
            f"Results20 feedback production requires {expected_cpus} Slurm CPUs"
        )
    commit = clean_commit()
    capacity = runtime(args.mode)
    experiment = load_experiment(CONFIG)
    if len(experiment.execution_assignments) != 240:
        raise RuntimeError("Results20 feedback assignment count changed")
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError("Results20 feedback audit panel changed")
    credentials(args.mode)
    path = owner(args.mode, commit, capacity, experiment)
    (execute(experiment) if args.mode == "execute" else audit(experiment, path))
    write_json_atomic(path / "completed.json", {"success": True, "finished_at": now()})


if __name__ == "__main__":
    main()
