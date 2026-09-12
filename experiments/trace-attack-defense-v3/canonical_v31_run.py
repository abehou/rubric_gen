"""Run the canonical nine-assignment User attack_defense_v3 candidate."""
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time

from dotenv import dotenv_values
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner, _exclusive_study_lease
from rubric_gen.submission_revision.study_validation import validate_completed_revision


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/canonical-v31")
TASKS = ("da-3-4", "da-11-1", "da-18-1")


def load_specs():
    specs = []
    for task in TASKS:
        path = BUNDLE / "canonical-v31" / f"{task}.yaml"
        exp = load_experiment(path)
        expected = {(task, rep, "user-simulator-red-team-trace") for rep in range(1, 4)}
        actual = {(a.task_id, a.replicate, a.condition_id) for a in exp.execution_assignments}
        if actual != expected or len(exp.execution_assignments) != 3 or exp.protocol.get("red_team_trace_version") != "attack_defense_v3.1":
            raise RuntimeError(f"canonical v3.1 scope/version differs: {path}")
        specs.append((task, exp, StudyRunner(StudyRunConfig(exp, Path(exp.dag["seed"]["output_dir"]), Path(exp.dag["paraphrase"]["output_dir"]), Path(exp.dag["revise"]["output_dir"]), 3, resume=Path(exp.dag["revise"]["output_dir"]).exists()))))
    return specs


def prepare(item):
    _, _, runner = item
    existed = runner.root.exists()
    runner.root.mkdir(parents=True, exist_ok=True)
    with _exclusive_study_lease(runner.root):
        runner._start_manifest(sorted(runner.experiment.assignments, key=lambda a: a.execution_order), existed)
        runner._prepare_pretreatment_rubric(runner.experiment.task_ids[0])


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("canonical v3.1 requires a 32-CPU Slurm allocation")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 1:
        raise RuntimeError("shared capacity policy differs")
    credentials = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    if not credentials.get("OPENAI_API_KEY"):
        raise RuntimeError("configured OpenAI credential absent")
    os.environ["OPENAI_API_KEY"] = str(credentials["OPENAI_API_KEY"])
    specs = load_specs()
    owner = RUN / "owners" / os.environ["SLURM_JOB_ID"]
    owner.mkdir(parents=True, exist_ok=True)
    write_json_atomic(owner / "launch.json", {
        "method": "attack_defense_v3.1_user_canonical",
        "job": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runtime": runtime,
        "cpus": 32,
        "assignment_workers": 9,
        "tasks": list(TASKS),
        "expected_assignments": 9,
        "configs": {str(exp.path): sha256_file(exp.path) for _, exp, _ in specs},
        "time": datetime.now(timezone.utc).isoformat(),
        "outcome_audits": False,
    })
    stop = threading.Event()
    def monitor():
        while not stop.is_set():
            rows = []
            for _, _, runner in specs:
                try:
                    rows.extend(json.loads((runner.root / "study.json").read_text())["records"])
                except (OSError, ValueError, KeyError):
                    pass
            write_json_atomic(BUNDLE / "canonical-v31-status.json", {"job": os.environ["SLURM_JOB_ID"], "statuses": dict(Counter(r["status"] for r in rows)), "time": datetime.now(timezone.utc).isoformat()})
            stop.wait(30)
    # Keep one assignment runner active at a time.  The prior canonical
    # control's three-way launch reached the 256G cgroup ceiling while
    # provider work remained otherwise healthy; this is an operational
    # resource bound and does not alter the scientific assignment set.
    with ThreadPoolExecutor(max_workers=1) as pool:
        list(pool.map(prepare, specs))
    runners = [(task, exp, StudyRunner(StudyRunConfig(exp, runner.seed_root, runner.paraphrase_root, runner.root, 3, resume=True))) for task, exp, runner in specs]
    threading.Thread(target=monitor, daemon=True).start()
    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            exits = list(pool.map(lambda item: item[2].run(), runners))
    finally:
        stop.set()
    write_json_atomic(owner / "revision-exits.json", {"exits": exits, "wall_seconds": time.monotonic() - start})
    if any(exits):
        raise RuntimeError("canonical v3.1 has incomplete assignments; successful outputs retained")
    rows = []
    for task, exp, runner in runners:
        ledger = json.loads((runner.root / "study.json").read_text())
        completed = terminal_records(exp, ledger)
        if len(completed) != 3 or any(r["status"] != "completed" for r in completed):
            raise RuntimeError(f"canonical v3.1 scope incomplete for {task}")
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for record in completed:
            path = runner.root / record["experiment_dir"]
            validate_completed_revision(path, assignments[record["assignment_id"]], exp, runner.seed_root, runner.paraphrase_root)
            rows.append({"task": task, "assignment_id": record["assignment_id"], "root": str(path), "experiment_id": exp.experiment_id})
    write_json_atomic(RUN / "completion.json", {"expected": 9, "completed": len(rows), "assignments": rows, "audits_launched": 0})
    print(json.dumps({"stage": "canonical_v31_complete", "assignments": len(rows), "outcome_audits": 0}), flush=True)


if __name__ == "__main__":
    main()
