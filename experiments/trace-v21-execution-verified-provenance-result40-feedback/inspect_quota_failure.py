"""Inspect persisted Results40 feedback work after the NAS1 quota incident."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


ROOT = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-feedback-policies-20260920"
)


def main() -> None:
    studies = []
    totals: Counter[str] = Counter()
    global_error_samples = {}
    for ledger_path in sorted((ROOT / "study").glob("*/*/*/study.json")):
        ledger = json.loads(ledger_path.read_text())
        records = ledger.get("records", [])
        statuses = Counter(str(row.get("status")) for row in records)
        errors = Counter(
            str(row.get("error_type")) for row in records if row.get("error_type")
        )
        attempts: Counter[str] = Counter()
        attempt_errors: Counter[str] = Counter()
        attempt_error_samples = {}
        attempts_with_output = 0
        attempt_files = 0
        for path in ledger_path.parent.rglob(
            "trace-defense-v2-requests/*/attempt-*.json"
        ):
            attempt_files += 1
            value = json.loads(path.read_text())
            attempts[str(value.get("status"))] += 1
            error_type = str(value.get("error_type"))
            attempt_errors[error_type] += 1
            attempt_error_samples.setdefault(
                error_type, str(value.get("error", ""))[:500]
            )
            global_error_samples.setdefault(
                error_type, str(value.get("error", ""))[:500]
            )
            attempts_with_output += int("output" in value)
        results = sum(
            1
            for _ in ledger_path.parent.rglob(
                "trace-defense-v2-requests/*/result.json"
            )
        )
        studies.append(
            {
                "path": str(ledger_path.parent),
                "status": ledger.get("status"),
                "records": dict(statuses),
                "errors": dict(errors),
                "trace_attempts": dict(attempts),
                "trace_attempt_errors": dict(attempt_errors),
                "trace_attempt_error_samples": attempt_error_samples,
                "trace_attempt_files": attempt_files,
                "trace_attempts_with_output": attempts_with_output,
                "trace_results": results,
            }
        )
        for key, value in statuses.items():
            totals[f"record:{key}"] += value
        for key, value in errors.items():
            totals[f"error:{key}"] += value
        for key, value in attempts.items():
            totals[f"trace_attempt:{key}"] += value
        for key, value in attempt_errors.items():
            totals[f"trace_attempt_error:{key}"] += value
        totals["trace_attempt_files"] += attempt_files
        totals["trace_attempts_with_output"] += attempts_with_output
        totals["trace_results"] += results

    receipt = {
        "study_count": len(studies),
        "totals": dict(sorted(totals.items())),
        "trace_attempt_error_samples": global_error_samples,
        "studies": studies,
    }
    output = ROOT / "receipts" / "quota-failure-inspection.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "receipt": str(output),
                **receipt["totals"],
                "study_count": len(studies),
                "trace_attempt_error_samples": global_error_samples,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
