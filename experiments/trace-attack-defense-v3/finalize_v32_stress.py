"""Provider-free completion validation for the nine v3.2 stress assignments."""
from __future__ import annotations

import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study_validation import validate_completed_revision

BUNDLE = Path(__file__).resolve().parent
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter3")
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def main() -> None:
    rows = []
    for task in TASKS:
        config = BUNDLE / "stress-v32" / f"v32-candidate-{task}.yaml"
        exp = load_experiment(config)
        if exp.protocol.get("red_team_trace_version") != "attack_defense_v3.2":
            raise RuntimeError(f"wrong recipe in {config}")
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        selected = terminal_records(exp, ledger)
        assignments = {item.assignment_id: item for item in exp.execution_assignments}
        if len(selected) != 3 or any(item.get("status") != "completed" for item in selected):
            raise RuntimeError(f"selected v3.2 scope incomplete: {task}")
        for record in selected:
            root = study / record["experiment_dir"]
            validate_completed_revision(root, assignments[record["assignment_id"]], exp,
                                        Path(exp.dag["seed"]["output_dir"]),
                                        Path(exp.dag["paraphrase"]["output_dir"]))
            rows.append({"task": task, "assignment_id": record["assignment_id"],
                         "root": str(root), "experiment_id": exp.experiment_id})
    receipt = {"kind": "trace_v3_2_stress_complete", "job": os.environ["SLURM_JOB_ID"],
               "expected_assignments": 9, "completed_assignments": len(rows),
               "provider_calls": 0, "recipe": "attack_defense_v3.2", "assignments": rows}
    write_json_atomic(RUN / "completion.json", receipt)
    write_json_atomic(BUNDLE / "stress-v32-finalization.json", receipt)
    print(json.dumps({"stage": "stress_v32_finalized", "completed": len(rows)}), flush=True)


if __name__ == "__main__":
    main()
