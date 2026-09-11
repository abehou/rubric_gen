"""Run the 9-assignment v2.1 User control and matched v3 stress arm."""
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
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress")
TASKS = ("da-15-1", "da-13-6", "da-18-5")
FLAVORS = ("v21-control", "v3-candidate")


def load_specs() -> list[tuple[str, object, StudyRunner]]:
    specs = []
    for flavor in FLAVORS:
        for task in TASKS:
            path = BUNDLE / "stress" / f"{flavor}-{task}.yaml"
            exp = load_experiment(path)
            expected = {(task, rep, "user-simulator-red-team-trace") for rep in range(1, 4)}
            actual = {(a.task_id, a.replicate, a.condition_id) for a in exp.execution_assignments}
            if actual != expected or len(exp.execution_assignments) != 3:
                raise RuntimeError(f"stress scope differs: {path}: {sorted(actual)}")
            version = exp.protocol.get("red_team_trace_version")
            if (flavor == "v21-control" and version != "attack_defense_v2.1") or (flavor == "v3-candidate" and version != "attack_defense_v3"):
                raise RuntimeError(f"unexpected recipe in {path}: {version}")
            runner = StudyRunner(
                StudyRunConfig(
                    exp,
                    Path(exp.dag["seed"]["output_dir"]),
                    Path(exp.dag["paraphrase"]["output_dir"]),
                    Path(exp.dag["revise"]["output_dir"]),
                    3,
                    resume=Path(exp.dag["revise"]["output_dir"]).exists(),
                )
            )
            specs.append((flavor, exp, runner))
    return specs


def prepare(spec: tuple[str, object, StudyRunner]) -> None:
    _, _, runner = spec
    existed = runner.root.exists()
    runner.root.mkdir(parents=True, exist_ok=True)
    with _exclusive_study_lease(runner.root):
        runner._start_manifest(sorted(runner.experiment.assignments, key=lambda a: a.execution_order), existed)
        runner._prepare_pretreatment_rubric(runner.experiment.task_ids[0])


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("stress run requires a 32-CPU Slurm allocation")
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
        "method": "attack_defense_v2.1_vs_v3_user_stress",
        "job": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runtime": runtime,
        "cpus": 32,
        "assignment_workers": 18,
        "tasks": list(TASKS),
        "flavors": list(FLAVORS),
        "expected_assignments": 18,
        "configs": {str(exp.path): sha256_file(exp.path) for _, exp, _ in specs},
        "time": datetime.now(timezone.utc).isoformat(),
        "outcome_audits": False,
        "shared_v21_source": SOURCE_STUDY if (SOURCE_STUDY := "/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/study/biomnibench-da-factorial-r10-5115fffdd1c0") else None,
    })
    stop = threading.Event()
    def monitor() -> None:
        while not stop.is_set():
            rows = []
            for _, _, runner in specs:
                try:
                    rows.extend(json.loads((runner.root / "study.json").read_text())["records"])
                except (OSError, ValueError, KeyError):
                    pass
            write_json_atomic(BUNDLE / "stress-status.json", {
                "job": os.environ["SLURM_JOB_ID"],
                "statuses": dict(Counter(r["status"] for r in rows)),
                "time": datetime.now(timezone.utc).isoformat(),
            })
            stop.wait(30)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(prepare, specs))
    runners = [
        (flavor, exp, StudyRunner(StudyRunConfig(exp, runner.seed_root, runner.paraphrase_root, runner.root, 3, resume=True)))
        for flavor, exp, runner in specs
    ]
    threading.Thread(target=monitor, daemon=True).start()
    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            exits = list(pool.map(lambda item: item[2].run(), runners))
    finally:
        stop.set()
    write_json_atomic(owner / "revision-exits.json", {"exits": exits, "wall_seconds": time.monotonic() - start})
    if any(exits):
        raise RuntimeError("stress run has incomplete assignments; successful outputs retained")
    rows = []
    for flavor, exp, runner in runners:
        ledger = json.loads((runner.root / "study.json").read_text())
        completed = terminal_records(exp, ledger)
        if len(completed) != 3 or any(r["status"] != "completed" for r in completed):
            raise RuntimeError(f"stress scope incomplete for {flavor}/{exp.task_ids[0]}")
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for record in completed:
            path = runner.root / record["experiment_dir"]
            validate_completed_revision(path, assignments[record["assignment_id"]], exp, runner.seed_root, runner.paraphrase_root)
            rows.append({"flavor": flavor, "task": exp.task_ids[0], "assignment_id": record["assignment_id"], "root": str(path), "experiment_id": exp.experiment_id})
    write_json_atomic(RUN / "completion.json", {"expected": 18, "completed": len(rows), "assignments": rows, "audits_launched": 0})
    print(json.dumps({"stage": "stress_complete", "assignments": len(rows), "outcome_audits": 0}), flush=True)


if __name__ == "__main__":
    main()
