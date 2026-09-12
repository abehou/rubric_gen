"""Resume the nine still-missing v3 consumer assignments in parallel.

The producer arm is already complete.  Each task runner is scoped to its own
three declared User assignments, and StudyRunner's native ledger resume skips
any assignment that became terminal before this invocation.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
from rubric_gen.submission_revision.study_validation import validate_completed_revision

from recover_stress_missing import BUNDLE, RUN, TASKS, inventory, specs, run_missing


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("consumer recovery requires a 32-CPU Slurm allocation")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError("shared capacity policy differs")
    credentials = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    if not credentials.get("OPENAI_API_KEY"):
        raise RuntimeError("configured OpenAI credential absent")
    os.environ["OPENAI_API_KEY"] = str(credentials["OPENAI_API_KEY"])

    producer = specs("v21-control")
    producer_before = [inventory(x) for x in producer]
    if any(
        d["status"] != "completed"
        for row in producer_before
        for d in row["records"]
    ):
        raise RuntimeError("producer arm is not complete; consumer recovery cannot start")

    consumer = specs("v3-candidate")
    before = [inventory(x) for x in consumer]
    owner = RUN / "owners" / os.environ["SLURM_JOB_ID"]
    owner.mkdir(parents=True, exist_ok=True)
    plan = {
        "kind": "trace_v3_stress_consumer_parallel_resume",
        "source_failed_job": "10402416",
        "producer_recovery_job": "10405463",
        "job": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=BUNDLE.parents[1], text=True).strip(),
        "runtime": runtime,
        "producer_before": producer_before,
        "consumer_before": before,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "consumer-recovery-plan.json", plan)
    write_json_atomic(BUNDLE / "stress-consumer-recovery-plan.json", plan)

    selected = {
        (row["flavor"], row["task"]): tuple(
            d["assignment_id"] for d in row["records"] if d["status"] != "completed"
        )
        for row in before
    }
    work = [(item, selected[(item[0], item[1])]) for item in consumer]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda pair: run_missing(*pair), work))
    if any(r.get("exit") or r.get("normalization_exit") for r in results):
        raise RuntimeError(f"consumer recovery remains incomplete: {results}")

    after = [inventory(x) for x in consumer]
    final_rows = []
    for item in producer + consumer:
        flavor, task, _, exp, runner = item
        ledger = json.loads((runner.root / "study.json").read_text())
        # Scoped studies intentionally retain non-selected factorial records as
        # pending.  StudyRunner therefore seals their ledger as
        # ``completed_scope``; treating that native terminal status as a
        # failure caused a false-negative after all consumer assignments had
        # completed.  Keep the selected-record validation below authoritative.
        if ledger.get("status") not in {"completed", "completed_scope"}:
            raise RuntimeError(f"final stress ledger is not complete: {flavor}/{task}")
        selected_records = [r for r in ledger["records"] if r["condition_id"] in exp.execution_conditions]
        if len(selected_records) != 3 or any(r["status"] != "completed" for r in selected_records):
            raise RuntimeError(f"final stress scope incomplete: {flavor}/{task}")
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for record in selected_records:
            exp_dir = runner.root / record["experiment_dir"]
            validate_completed_revision(
                exp_dir, assignments[record["assignment_id"]], exp,
                runner.seed_root, runner.paraphrase_root,
            )
            final_rows.append({
                "flavor": flavor, "task": task,
                "assignment_id": record["assignment_id"], "root": str(exp_dir),
                "experiment_id": exp.experiment_id,
            })
    receipt = {
        "kind": "trace_v3_stress_missing_only_recovery_complete",
        "source_failed_job": "10402416",
        "producer_recovery_job": "10405463",
        "consumer_recovery_job": os.environ["SLURM_JOB_ID"],
        "job": os.environ["SLURM_JOB_ID"],
        "producer_before": producer_before,
        "consumer_before": before,
        "dispatch": results,
        "consumer_after": after,
        "expected_assignments": 18,
        "completed_assignments": len(final_rows),
        "audits_launched": 0,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "recovery-complete.json", receipt)
    write_json_atomic(RUN / "recovery-complete.json", receipt)
    write_json_atomic(BUNDLE / "stress-recovery-complete.json", receipt)
    print(json.dumps({"stage": "stress_consumer_parallel_recovery_complete", "completed": len(final_rows), "job": os.environ["SLURM_JOB_ID"]}), flush=True)


if __name__ == "__main__":
    main()
