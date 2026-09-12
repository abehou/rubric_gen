"""Finalize a completed scoped stress cohort without model/provider calls.

The native scoped StudyRunner status is ``completed_scope`` because the study
ledger intentionally retains the other declared factorial assignments as
pending.  This receipt step validates the selected User assignments and their
sealed revision evidence; it never runs StudyRunner or changes a ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.study_validation import validate_completed_revision

from recover_stress_missing import BUNDLE, RUN, specs, inventory


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("stress finalization requires a Slurm compute job")
    items = specs("v21-control") + specs("v3-candidate")
    rows = []
    inventories = []
    for flavor, task, path, exp, runner in items:
        detail = inventory((flavor, task, path, exp, runner))
        inventories.append(detail)
        ledger = json.loads((runner.root / "study.json").read_text())
        selected = terminal_records(exp, ledger)
        if len(selected) != 3 or any(record.get("status") != "completed" for record in selected):
            raise RuntimeError(f"selected stress scope incomplete: {flavor}/{task}")
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for record in selected:
            exp_dir = runner.root / record["experiment_dir"]
            validate_completed_revision(
                exp_dir, assignments[record["assignment_id"]], exp,
                runner.seed_root, runner.paraphrase_root,
            )
            rows.append({
                "flavor": flavor,
                "task": task,
                "assignment_id": record["assignment_id"],
                "root": str(exp_dir),
                "experiment_id": exp.experiment_id,
                "ledger_status": ledger.get("status"),
            })
    if len(rows) != 18:
        raise RuntimeError(f"expected 18 selected stress assignments, found {len(rows)}")
    receipt = {
        "kind": "trace_v3_stress_missing_only_recovery_complete",
        "source_failed_job": "10402416",
        "producer_recovery_job": "10405463",
        "consumer_recovery_job": "10405844",
        "finalization_job": os.environ["SLURM_JOB_ID"],
        "expected_assignments": 18,
        "completed_assignments": len(rows),
        "provider_calls": 0,
        "audits_launched": 0,
        "native_scope_statuses": sorted({r["ledger_status"] for r in rows}),
        "assignments": rows,
        "inventories": inventories,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    owner = RUN / "owners" / os.environ["SLURM_JOB_ID"]
    owner.mkdir(parents=True, exist_ok=True)
    write_json_atomic(owner / "recovery-complete.json", receipt)
    write_json_atomic(RUN / "recovery-complete.json", receipt)
    write_json_atomic(BUNDLE / "stress-recovery-complete.json", receipt)
    print(json.dumps({"stage": "stress_recovery_finalized", "completed": len(rows), "provider_calls": 0}), flush=True)


if __name__ == "__main__":
    main()
