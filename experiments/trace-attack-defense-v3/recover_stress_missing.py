"""Resume only incomplete assignments from the failed v3 stress invocation.

The producer study is recovered first.  Completed assignments are never selected
in an invocation scope; after the missing scopes finish, a no-provider full
resume normalizes each ledger so the final stress receipt has the native
unscoped terminal identity.  The consumer arm is then run only for its missing
assignments, using the already sealed producer studies.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
from rubric_gen.submission_revision.study_validation import validate_completed_revision


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter1")
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def specs(flavor: str):
    out = []
    for task in TASKS:
        path = BUNDLE / "stress" / f"{flavor}-{task}.yaml"
        exp = load_experiment(path)
        expected = {(task, rep, "user-simulator-red-team-trace") for rep in range(1, 4)}
        actual = {(a.task_id, a.replicate, a.condition_id) for a in exp.execution_assignments}
        if actual != expected or len(exp.execution_assignments) != 3:
            raise RuntimeError(f"unexpected stress scope: {path}")
        expected_version = "attack_defense_v2.1" if flavor == "v21-control" else "attack_defense_v3"
        if exp.protocol.get("red_team_trace_version") != expected_version:
            raise RuntimeError(f"unexpected recipe in {path}: {exp.protocol.get('red_team_trace_version')}")
        runner = StudyRunner(StudyRunConfig(
            exp, Path(exp.dag["seed"]["output_dir"]),
            Path(exp.dag["paraphrase"]["output_dir"]),
            Path(exp.dag["revise"]["output_dir"]), 1, resume=True,
        ))
        out.append((flavor, task, path, exp, runner))
    return out


def ledger_rows(runner: StudyRunner):
    path = runner.root / "study.json"
    if not path.exists():
        return {}, None
    raw = json.loads(path.read_text())
    return {str(r["assignment_id"]): r for r in raw.get("records", [])}, raw


def inventory(item):
    flavor, task, path, exp, runner = item
    rows, raw = ledger_rows(runner)
    details = []
    for assignment in exp.execution_assignments:
        record = rows.get(assignment.assignment_id)
        status = record.get("status") if record else "missing_record"
        exp_dir = runner._experiment_dir(assignment)
        partial = exp_dir.exists()
        details.append({
            "assignment_id": assignment.assignment_id,
            "status": status,
            "experiment_dir": str(exp_dir),
            "partial_workspace": partial,
            "error_type": record.get("error_type") if record else None,
            "error": record.get("error") if record else None,
        })
    return {
        "flavor": flavor, "task": task, "config": str(path),
        "config_sha256": sha256_file(path),
        "experiment_id": exp.experiment_id,
        "study_root": str(runner.root),
        "study_status": raw.get("status") if raw else "absent",
        "records": details,
        "counts": dict(Counter(d["status"] for d in details)),
    }


def run_missing(item, selected: tuple[str, ...]):
    flavor, task, path, exp, runner = item
    if not selected:
        return {"flavor": flavor, "task": task, "selected": [], "exit": 0, "mode": "none"}
    scoped = StudyRunner(StudyRunConfig(
        exp, runner.seed_root, runner.paraphrase_root, runner.root, 1,
        resume=True, assignment_ids=selected,
    ))
    exit_code = scoped.run()
    if exit_code:
        return {
            "flavor": flavor, "task": task, "selected": list(selected),
            "exit": exit_code, "normalization_exit": None,
            "mode": "scoped_missing_resume",
        }
    # Convert a successful scoped invocation back to the native full-study
    # terminal form.  This performs validation only when no assignments remain.
    full = StudyRunner(StudyRunConfig(
        exp, runner.seed_root, runner.paraphrase_root, runner.root, 1, resume=True,
    ))
    full_exit = full.run()
    return {
        "flavor": flavor, "task": task, "selected": list(selected),
        "exit": exit_code, "normalization_exit": full_exit, "mode": "scoped_missing_resume",
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("stress recovery requires a 32-CPU Slurm allocation")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError("shared capacity policy differs")
    credentials = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    if not credentials.get("OPENAI_API_KEY"):
        raise RuntimeError("configured OpenAI credential absent")
    os.environ["OPENAI_API_KEY"] = str(credentials["OPENAI_API_KEY"])

    producer = specs("v21-control")
    before = [inventory(x) for x in producer]
    owner = RUN / "owners" / os.environ["SLURM_JOB_ID"]
    owner.mkdir(parents=True, exist_ok=True)
    plan = {
        "kind": "trace_v3_stress_missing_only_recovery",
        "source_failed_job": "10402416",
        "job": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runtime": runtime,
        "before": before,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "recovery-plan.json", plan)
    write_json_atomic(BUNDLE / "stress-recovery-plan.json", plan)

    results = []
    for item in producer:
        row = next(x for x in before if x["flavor"] == item[0] and x["task"] == item[1])
        selected = tuple(d["assignment_id"] for d in row["records"] if d["status"] != "completed")
        results.append(run_missing(item, selected))
    if any(r.get("exit") or r.get("normalization_exit") for r in results):
        raise RuntimeError(f"producer recovery remains incomplete: {results}")

    # Consumers were not started by 10402416.  Construct them only after every
    # producer study is complete: their native loader validates that source
    # identity before a runner can even be instantiated.
    consumer = specs("v3-candidate")
    before.extend(inventory(x) for x in consumer)
    # Still derive scope from the ledger so this remains missing-only if a
    # future partial invocation exists.
    for item in consumer:
        row = next(x for x in before if x["flavor"] == item[0] and x["task"] == item[1])
        selected = tuple(d["assignment_id"] for d in row["records"] if d["status"] != "completed")
        results.append(run_missing(item, selected))
    if any(r.get("exit") or r.get("normalization_exit") for r in results):
        raise RuntimeError(f"consumer recovery remains incomplete: {results}")

    after = [inventory(x) for x in producer + consumer]
    final_rows = []
    for item in producer + consumer:
        flavor, task, _, exp, runner = item
        ledger = json.loads((runner.root / "study.json").read_text())
        selected = [r for r in ledger["records"] if r["status"] == "completed"]
        if len(selected) != 3 or ledger.get("status") != "completed":
            raise RuntimeError(f"final stress scope incomplete: {flavor}/{task}")
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for record in selected:
            exp_dir = runner.root / record["experiment_dir"]
            validate_completed_revision(exp_dir, assignments[record["assignment_id"]], exp, runner.seed_root, runner.paraphrase_root)
            final_rows.append({"flavor": flavor, "task": task, "assignment_id": record["assignment_id"], "root": str(exp_dir), "experiment_id": exp.experiment_id})
    receipt = {
        "kind": "trace_v3_stress_missing_only_recovery_complete",
        "source_failed_job": "10402416", "job": os.environ["SLURM_JOB_ID"],
        "before": before, "dispatch": results, "after": after,
        "expected_assignments": 18, "completed_assignments": len(final_rows),
        "audits_launched": 0,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "recovery-complete.json", receipt)
    write_json_atomic(RUN / "recovery-complete.json", receipt)
    print(json.dumps({"stage": "stress_missing_only_recovery_complete", "completed": len(final_rows), "job": os.environ["SLURM_JOB_ID"]}), flush=True)


if __name__ == "__main__":
    main()
