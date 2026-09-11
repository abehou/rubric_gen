"""Provider-free validation of the completed canonical v2.1 User dev3 control."""
from __future__ import annotations

from datetime import datetime, timezone
import json, os, socket, subprocess
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.study_validation import validate_completed_revision

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911") / "control-v21-compatible"
TASKS = ("da-3-4", "da-11-1", "da-18-1")


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("validation must run on Slurm compute")
    rows = []
    for task in TASKS:
        config = BUNDLE / "control-v21-compatible" / f"{task}.yaml"
        exp = load_experiment(config)
        study = Path(exp.dag["revise"]["output_dir"])
        ledger_path = study / "study.json"
        ledger = json.loads(ledger_path.read_text())
        completed = terminal_records(exp, ledger)
        if len(completed) != 3 or any(r["status"] != "completed" for r in completed):
            raise RuntimeError(f"incomplete ledger for {task}: {len(completed)}")
        assignments = {a.assignment_id: a for a in exp.assignments}
        task_rows = []
        for record in sorted(completed, key=lambda r: r["assignment_id"]):
            exp_dir = study / record["experiment_dir"]
            validate_completed_revision(
                exp_dir, assignments[record["assignment_id"]], exp,
                Path(exp.dag["seed"]["output_dir"]),
                Path(exp.dag["paraphrase"]["output_dir"]),
            )
            state = json.loads((exp_dir / "state.json").read_text())
            task_rows.append({
                "assignment_id": record["assignment_id"],
                "experiment_dir": record["experiment_dir"],
                "state_sha256": sha256_file(exp_dir / "state.json"),
                "submission_count": len(state["submission_ids"]),
                "last_submission_id": state["submission_ids"][-1],
                "stop_reason": state["stop_reason"],
            })
        rows.append({
            "task": task, "config": str(config),
            "config_sha256": sha256_file(config),
            "study": str(study),
            "study_sha256": sha256_file(ledger_path),
            "assignments": task_rows,
        })
    receipt = {
        "kind": "trace_v3_control_provider_free_validation",
        "method": "attack_defense_v2.1",
        "job": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "validator_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "expected_assignments": 9, "validated_assignments": sum(len(x["assignments"]) for x in rows),
        "tasks": rows,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "provider_calls": 0,
    }
    write_json_atomic(RUN / "control-validation-receipt.json", receipt)
    print(json.dumps({"stage": "control_validation_complete", "assignments": receipt["validated_assignments"]}), flush=True)


if __name__ == "__main__":
    main()
