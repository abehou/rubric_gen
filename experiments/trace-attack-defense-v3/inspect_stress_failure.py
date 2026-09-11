"""Provider-free inventory of the failed v3 stress producer phase."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path


RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter1")
BUNDLE = Path(__file__).resolve().parent
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def read(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        return {"_read_error": f"{type(exc).__name__}: {exc}"}


def stderr_tail() -> list[str]:
    path = BUNDLE / "stress-10402416.err"
    if not path.exists():
        return []
    return path.read_text(errors="replace").splitlines()[-160:]


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("compute-only inspection")
    flavors = {}
    for flavor in ("v21-control", "v3-candidate"):
        tasks = {}
        for task in TASKS:
            root = RUN / flavor / task / "study"
            ledgers = sorted(root.glob("*/study.json"))
            ledger_path = ledgers[-1] if ledgers else None
            ledger = read(ledger_path) if ledger_path else None
            records = ledger.get("records", []) if isinstance(ledger, dict) else []
            status_counts = Counter(str(r.get("status")) for r in records)
            assignments = []
            for rec in records:
                exp_root = root / str(rec.get("experiment_dir", ""))
                state_paths = sorted(exp_root.glob("state.json"))
                state = read(state_paths[0]) if state_paths else None
                checkpoints = [str(p) for p in sorted(exp_root.glob("**/checkpoint-*")) if p.is_dir()][:100]
                attempts_root = RUN / flavor / task / "study" / "execution-attempts" / str(rec.get("assignment_id"))
                attempts = []
                if attempts_root.exists():
                    for attempt in sorted(attempts_root.glob("attempt-*.json")):
                        attempts.append({"path": str(attempt), "record": read(attempt)})
                assignments.append({
                    "assignment_id": rec.get("assignment_id"),
                    "status": rec.get("status"),
                    "experiment_dir": str(exp_root),
                    "record": rec,
                    "state": state,
                    "state_exists": bool(state_paths),
                    "checkpoint_dirs": checkpoints,
                    "failure_attempts": attempts,
                })
            tasks[task] = {
                "study_root": str(root),
                "ledger": str(ledger_path) if ledger_path else None,
                "status_counts": dict(status_counts),
                "records": assignments,
                "study_stderr_tail": stderr_tail(),
            }
        flavors[flavor] = tasks
    out = {
        "kind": "trace_v3_stress_failure_inventory",
        "source_job": "10402416",
        "run_root": str(RUN),
        "time": datetime.now(timezone.utc).isoformat(),
        "flavors": flavors,
    }
    path = BUNDLE / "stress-failure-inventory-10402416.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"stage": "stress_failure_inventory_complete", "output": str(path), "run_root": str(RUN)}), flush=True)


if __name__ == "__main__":
    main()
