"""Read-only compact summary for a Results40 audit owner log on compute NFS."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys


RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918")


def main() -> None:
    job_id = sys.argv[1]
    log = RUN / "logs" / f"audit-{job_id}.out"
    err = RUN / "logs" / f"audit-{job_id}.err"
    rows = []
    for line in log.read_text(errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "scope" in value:
            rows.append(value)
    print(json.dumps({
        "job_id": job_id,
        "scope_rows": len(rows),
        "by_panel": dict(Counter(
            "sol_opus" if "sol-opus" in str(row["scope"]) else "gemini"
            for row in rows
        )),
        "failed_scopes": [row["scope"] for row in rows if row.get("exit_code")],
        "last_scopes": [
            {"scope": row["scope"], "exit_code": row.get("exit_code")}
            for row in rows[-8:]
        ],
        "stderr_tail": err.read_text(errors="replace").splitlines()[-20:] if err.exists() else [],
    }, indent=2))

    for row in rows:
        if not row.get("exit_code"):
            continue
        scope_log = Path(str(row["log"]))
        print(json.dumps({
            "failed_scope": row["scope"],
            "scope_log_tail": scope_log.read_text(errors="replace").splitlines()[-30:]
            if scope_log.exists() else ["missing scope log"],
        }, indent=2))

    status = RUN / "audit-status.json"
    if status.exists():
        value = json.loads(status.read_text())
        print(json.dumps({
            "audit_status_job_id": value.get("job_id"),
            "complete": value.get("complete"),
            "finished_at": value.get("finished_at"),
            "gemini_stopped_after_first_failed_scope": value.get("gemini_stopped_after_first_failed_scope"),
            "recorded_scope_count": len(value.get("scopes", {})),
        }, indent=2))

    old_static = RUN / "audit-gemini" / "old20" / "static-full"
    failures = []
    for summary_path in sorted(old_static.glob("**/summary.json")):
        try:
            value = json.loads(summary_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for failure in value.get("judge_failures", ()):
            failures.append({
                "summary": str(summary_path.relative_to(old_static)),
                "model": failure.get("model"),
                "judgment_key": failure.get("judgment_key"),
                "error": str(failure.get("error", ""))[:1200],
            })
        for record in value.get("records", ()):
            if record.get("status") == "failed":
                failures.append({
                    "summary": str(summary_path.relative_to(old_static)),
                    "model": record.get("model"),
                    "case_id": record.get("case_id"),
                    "error": str(record.get("error", ""))[:1200],
                })
    print(json.dumps({"old20_static_full_failures": failures}, indent=2))


if __name__ == "__main__":
    main()
