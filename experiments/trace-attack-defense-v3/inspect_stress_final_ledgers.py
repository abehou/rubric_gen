"""Provider-free final ledger/status inspection after missing-only stress recovery."""
from __future__ import annotations

import json
import os
from pathlib import Path

from recover_stress_missing import BUNDLE, RUN, TASKS, specs, inventory


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("compute-only inspection")
    rows = []
    for flavor in ("v21-control", "v3-candidate"):
        for item in specs(flavor):
            detail = inventory(item)
            ledger_path = Path(detail["study_root"]) / "study.json"
            ledger = json.loads(ledger_path.read_text())
            selected = [r for r in ledger.get("records", []) if r.get("condition_id") in item[3].execution_conditions]
            rows.append({
                "flavor": flavor,
                "task": detail["task"],
                "study_root": detail["study_root"],
                "ledger_status": ledger.get("status"),
                "execution_conditions": list(item[3].execution_conditions or ()),
                "record_statuses": {r["assignment_id"]: r.get("status") for r in selected},
                "all_record_statuses": {r["assignment_id"]: r.get("status") for r in ledger.get("records", [])},
                "selected_count": len(selected),
                "selected_completed": sum(r.get("status") == "completed" for r in selected),
                "all_count": len(ledger.get("records", [])),
            })
    out = BUNDLE / "stress-final-ledger-inspection-10405844.json"
    out.write_text(json.dumps({"job": os.environ["SLURM_JOB_ID"], "rows": rows}, indent=2) + "\n")
    print(json.dumps({"output": str(out), "rows": rows}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
