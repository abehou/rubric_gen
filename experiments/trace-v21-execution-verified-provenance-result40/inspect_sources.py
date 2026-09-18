"""Read only the small queue6 study receipts needed for native g1 reuse."""
from __future__ import annotations

import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic

from make_configs import BUNDLE, ROOT, TASKS, old_task_root, source_config


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("source receipt inspection must run on Slurm")
    sources = {}
    inspected = {}
    for task in TASKS[:10]:
        parent = old_task_root(task) / "study"
        rows = []
        for study in sorted(parent.iterdir()) if parent.is_dir() else []:
            ledger_path = study / "study.json"
            if not ledger_path.is_file():
                continue
            ledger = json.loads(ledger_path.read_text())
            pool = study / "pretreatment-rubrics"
            row = {
                "study_dir": str(study),
                "experiment_id": ledger.get("experiment_id"),
                "status": ledger.get("status"),
                "records": len(ledger.get("records", [])),
                "completed": sum(r.get("status") == "completed" for r in ledger.get("records", [])),
                "pretreatment_pool": str(pool),
                "pretreatment_exists": pool.is_dir(),
            }
            rows.append(row)
        inspected[task] = rows
        eligible = [
            row for row in rows
            if row["status"] in {"completed", "completed_scope"} and row["pretreatment_exists"]
        ]
        if len(eligible) == 1:
            row = eligible[0]
            sources[task] = {
                "experiment": str(source_config(task)),
                "study_dir": row["study_dir"],
                "experiment_id": row["experiment_id"],
            }
        elif len(eligible) > 1:
            raise RuntimeError(f"ambiguous completed pretreatment sources for {task}: {eligible}")
    write_json_atomic(BUNDLE / "pretreatment-sources.json", sources)
    write_json_atomic(BUNDLE / "receipts/pretreatment-source-inspection.json", {
        "job_id": os.environ["SLURM_JOB_ID"], "provider_calls": 0,
        "sources": sources, "inspected": inspected,
    })
    print(json.dumps({"sources": sorted(sources), "count": len(sources)}), flush=True)


if __name__ == "__main__":
    main()
