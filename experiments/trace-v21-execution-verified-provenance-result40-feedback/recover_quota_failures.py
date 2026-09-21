"""Rearm only evidenced response-free operational RTT requests."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic


RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-feedback-policies-20260920"
)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _recoverable_operational_failure(attempt: dict) -> bool:
    if (
        attempt.get("status") != "provider_failure"
        or attempt.get("permanent")
        or "output" in attempt
        or "result" in attempt
    ):
        return False
    error_type = attempt.get("error_type")
    error = str(attempt.get("error", ""))
    return (
        error_type == "OSError" and "Disk quota exceeded" in error
    ) or (
        error_type == "RuntimeError"
        and error.startswith("OPENAI_API_KEY must be set for the ")
    ) or (
        error_type == "RateLimitError"
        and "You have no credits remaining." in error
        and "'type': 'insufficient_quota'" in error
        and "'code': 'credit_balance_exhausted'" in error
    )


def response_free_quota_requests(experiment_dir: Path) -> list[Path]:
    """Return requests containing only observed response-free failures."""

    root = experiment_dir / "trace-defense-v2-requests"
    if not root.exists():
        return []
    if root.is_symlink():
        raise RuntimeError(f"request root is a symlink: {root}")
    failed = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or directory.is_symlink():
            continue
        if (directory / "result.json").exists():
            continue
        attempt_paths = sorted(directory.glob("attempt-*.json"))
        if not attempt_paths:
            continue
        attempts = [_read(path) for path in attempt_paths]
        if not all(_recoverable_operational_failure(attempt) for attempt in attempts):
            raise RuntimeError(
                f"request is not an exact response-free operational failure: {directory}"
            )
        failed.append(directory)
    return failed


def plan(run: Path = RUN) -> list[dict]:
    recovery = []
    for ledger_path in sorted((run / "study").glob("*/*/*/study.json")):
        ledger = _read(ledger_path)
        for record in ledger.get("records", []):
            if record.get("status") == "completed":
                continue
            if (
                record.get("status") == "failed"
                and record.get("automatic_recovery_exhausted")
                and record.get("error_type") == "RubricProposerProviderError"
            ):
                experiment_dir = ledger_path.parent / str(record["experiment_dir"])
                requests = response_free_quota_requests(experiment_dir)
                if not requests:
                    raise RuntimeError(
                        "exhausted proposer failure has no response-free operational request: "
                        f"{record['assignment_id']}"
                    )
                recovery.append(
                    {
                        "ledger": str(ledger_path),
                        "assignment_id": record["assignment_id"],
                        "requests": [str(path) for path in requests],
                    }
                )
    return recovery


def apply_recovery(run: Path, recovery: list[dict]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = run / "recovery-evidence" / f"response-free-operational-{stamp}"
    by_ledger: dict[Path, list[dict]] = {}
    for row in recovery:
        by_ledger.setdefault(Path(row["ledger"]), []).append(row)
    for ledger_path, rows in by_ledger.items():
        ledger = _read(ledger_path)
        records = {record["assignment_id"]: record for record in ledger["records"]}
        for row in rows:
            assignment_id = str(row["assignment_id"])
            record = records[assignment_id]
            destination = archive / assignment_id
            destination.mkdir(parents=True, exist_ok=False)
            for raw in row["requests"]:
                source = Path(raw)
                source.rename(destination / source.name)
            record.update(
                automatic_recovery_exhausted=False,
                automatic_attempt_count=0,
                next_automatic_action=(
                    "explicit resume after archived response-free operational failure"
                ),
                operational_recovery_archive=str(destination),
            )
        write_json_atomic(ledger_path, ledger)
    receipt = run / "receipts" / f"quota-failure-recovery-{stamp}.json"
    write_json_atomic(
        receipt,
        {
            "applied_at": stamp,
            "reason": (
                "response-free missing credential, NAS1 runtime-journal quota, "
                "or confirmed external credit-exhaustion failures"
            ),
            "response_free_assignments": len(recovery),
            "archive": str(archive),
            "recovery": recovery,
        },
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--run", type=Path, default=RUN)
    args = parser.parse_args()
    recovery = plan(args.run)
    result = {
        "run": str(args.run),
        "response_free_assignments": len(recovery),
        "recovery": recovery,
    }
    if args.apply:
        result["receipt"] = str(apply_recovery(args.run, recovery))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
