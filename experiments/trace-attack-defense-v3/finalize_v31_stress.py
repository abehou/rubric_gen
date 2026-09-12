"""Provider-free finalizer for the nine-assignment v3.1 stress cohort."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study_validation import validate_completed_revision

BUNDLE = Path(__file__).resolve().parent
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter2")
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("v3.1 stress finalization requires Slurm")
    rows = []
    for task in TASKS:
        config = BUNDLE / "stress-v31" / f"v31-candidate-{task}.yaml"
        exp = load_experiment(config)
        if exp.protocol.get("red_team_trace_version") != "attack_defense_v3.1":
            raise RuntimeError(f"wrong recipe in {config}")
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        selected = terminal_records(exp, ledger)
        if len(selected) != 3 or any(r.get("status") != "completed" for r in selected):
            raise RuntimeError(f"selected v3.1 scope incomplete: {task}")
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for record in selected:
            exp_dir = study / record["experiment_dir"]
            validate_completed_revision(
                exp_dir, assignments[record["assignment_id"]], exp,
                Path(exp.dag["seed"]["output_dir"]), Path(exp.dag["paraphrase"]["output_dir"]),
            )
            rows.append({
                "task": task,
                "assignment_id": record["assignment_id"],
                "root": str(exp_dir),
                "experiment_id": exp.experiment_id,
                "config": str(config),
                "config_sha256": __import__("hashlib").sha256(config.read_bytes()).hexdigest(),
                "ledger_status": ledger.get("status"),
            })
    if len(rows) != 9:
        raise RuntimeError(f"expected 9 v3.1 assignments, found {len(rows)}")
    receipt = {
        "kind": "trace_v3_1_stress_complete",
        "job": os.environ["SLURM_JOB_ID"],
        "expected_assignments": 9,
        "completed_assignments": len(rows),
        "provider_calls": 0,
        "audits_launched": 0,
        "recipe": "attack_defense_v3.1",
        "source_control": "stress-iter1/v21-control",
        "assignments": rows,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(RUN / "v31-finalization.json", receipt)
    write_json_atomic(BUNDLE / "stress-v31-finalization.json", receipt)
    print(json.dumps({"stage": "stress_v31_finalized", "completed": len(rows), "provider_calls": 0}), flush=True)


if __name__ == "__main__":
    main()
