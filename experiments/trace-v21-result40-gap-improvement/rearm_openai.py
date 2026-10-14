"""Rearm the three reviewed response-free OpenAI billing requests."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import _exclusive_study_lease

from make_configs import ROOT, RUN, config_path


CREDIT_ERROR = (
    "Error code: 429 - {'error': {'message': 'You have no credits remaining. "
    "Add credits to continue using the API at "
    "https://platform.openai.com/settings/organization/billing/.', "
    "'type': 'insufficient_quota', 'param': None, "
    "'code': 'credit_balance_exhausted'}}"
)


@dataclass(frozen=True)
class RecoveryRequest:
    request_key: str
    stage: str
    expected_errors: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RecoveryCase:
    task_id: str
    assignment_id: str
    failed_request_key: str
    requests: tuple[RecoveryRequest, ...]


CASES = (
    RecoveryCase(
        task_id="da-26-4",
        assignment_id=(
            "da-26-4--rep-001--solver-luna--"
            "user-simulator-red-team-trace-gap-improvement"
        ),
        failed_request_key=(
            "41b5c9593acbf911b0774bce750dcb0999cbbbea167103ea349caf9e9c73817e"
        ),
        requests=(
            RecoveryRequest(
                request_key=(
                    "41b5c9593acbf911b0774bce750dcb0999cbbbea167103ea349caf9e9c73817e"
                ),
                stage="quality",
                expected_errors=(("RateLimitError", CREDIT_ERROR),) * 4,
            ),
            RecoveryRequest(
                request_key=(
                    "6746b850f6ebe076603c0be513d626f64d552e2f8a3e325f5e09575ec52180e3"
                ),
                stage="quality",
                expected_errors=(("RateLimitError", CREDIT_ERROR),) * 4,
            ),
        ),
    ),
    RecoveryCase(
        task_id="da-20-4",
        assignment_id=(
            "da-20-4--rep-001--solver-luna--"
            "user-simulator-red-team-trace-gap-improvement"
        ),
        failed_request_key=(
            "2bbd6e61dd8e265d833894b0a547d6f7eff6f370c9f6c9d64eee5f6cfa73d7b6"
        ),
        requests=(
            RecoveryRequest(
                request_key=(
                    "2bbd6e61dd8e265d833894b0a547d6f7eff6f370c9f6c9d64eee5f6cfa73d7b6"
                ),
                stage="enforcement",
                expected_errors=(
                    ("APIConnectionError", "Connection error."),
                    ("RateLimitError", CREDIT_ERROR),
                    ("RateLimitError", CREDIT_ERROR),
                    ("RateLimitError", CREDIT_ERROR),
                ),
            ),
        ),
    ),
)


def clean_commit() -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if dirty.strip():
        raise RuntimeError("OpenAI billing recovery source must be a clean commit")
    return commit


def study_for(case: RecoveryCase) -> Path:
    experiment = load_experiment(config_path(case.task_id))
    return Path(experiment.dag["revise"]["output_dir"])


def read_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} is not an object: {path}")
    return value


def inspect_case(study: Path, case: RecoveryCase) -> dict[str, object]:
    ledger_path = study / "study.json"
    ledger = read_object(ledger_path, "study ledger")
    records = [
        record
        for record in ledger.get("records", [])
        if record.get("assignment_id") == case.assignment_id
    ]
    if len(records) != 1:
        raise RuntimeError(f"unexpected assignment ledger scope: {case.assignment_id}")
    record = records[0]
    experiment_dir = study / str(record.get("experiment_dir"))
    request_root = experiment_dir / "trace-defense-v2-requests"
    requests_by_key = {request.request_key: request for request in case.requests}
    if len(requests_by_key) != len(case.requests):
        raise RuntimeError(f"duplicate reviewed request key: {case.assignment_id}")
    failed_request = requests_by_key.get(case.failed_request_key)
    if failed_request is None:
        raise RuntimeError(f"unreviewed ledger request key: {case.assignment_id}")
    expected_failure_path = request_root / failed_request.request_key
    expected_error = (
        f"{failed_request.stage}: provider failure at {expected_failure_path}"
    )
    if not (
        record.get("status") == "failed"
        and record.get("automatic_recovery_exhausted") is True
        and record.get("error_type") == "RubricProposerProviderError"
        and record.get("error") == expected_error
    ):
        raise RuntimeError(f"assignment is not the reviewed billing failure: {case.assignment_id}")

    if request_root.is_symlink() or not request_root.is_dir():
        raise RuntimeError(f"invalid request root: {request_root}")
    incomplete = []
    for directory in sorted(request_root.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            raise RuntimeError(f"invalid request directory: {directory}")
        attempts = sorted(directory.glob("attempt-*.json"))
        if attempts and not (directory / "result.json").exists():
            incomplete.append(directory)
    expected_paths = sorted(request_root / key for key in requests_by_key)
    if incomplete != expected_paths:
        raise RuntimeError(
            f"unexpected incomplete request scope for {case.assignment_id}: {incomplete}"
        )

    request_evidence = []
    for request in case.requests:
        request_path = request_root / request.request_key
        attempt_paths = sorted(request_path.glob("attempt-*.json"))
        expected_names = [
            f"attempt-{index:03d}.json"
            for index in range(1, len(request.expected_errors) + 1)
        ]
        if [path.name for path in attempt_paths] != expected_names:
            raise RuntimeError(f"billing attempt set changed: {request_path}")
        attempts = [read_object(path, "billing attempt") for path in attempt_paths]
        for index, (attempt, expected) in enumerate(
            zip(attempts, request.expected_errors, strict=True), start=1
        ):
            if not (
                attempt.get("attempt") == index
                and attempt.get("request_sha256") == request.request_key
                and attempt.get("stage") == request.stage
                and attempt.get("status") == "provider_failure"
                and attempt.get("permanent") is False
                and attempt.get("error_type") == expected[0]
                and attempt.get("error") == expected[1]
                and all(
                    key not in attempt for key in ("output", "response", "result")
                )
            ):
                raise RuntimeError(
                    "billing attempt is not the reviewed response-free failure: "
                    f"{attempt_paths[index - 1]}"
                )
        request_evidence.append(
            {
                "request_dir": str(request_path),
                "request_key": request.request_key,
                "stage": request.stage,
                "attempts": [
                    {"name": path.name, "sha256": sha256_file(path)}
                    for path in attempt_paths
                ],
                "provider_responses": 0,
            }
        )
    return {
        "task_id": case.task_id,
        "assignment_id": case.assignment_id,
        "study": str(study),
        "ledger_path": str(ledger_path),
        "requests": request_evidence,
        "provider_responses": 0,
    }


def discover_case(study: Path, case: RecoveryCase) -> dict[str, object]:
    ledger = read_object(study / "study.json", "study ledger")
    record = next(
        (
            record
            for record in ledger.get("records", [])
            if record.get("assignment_id") == case.assignment_id
        ),
        None,
    )
    if record is None:
        raise RuntimeError(f"assignment is absent: {case.assignment_id}")
    experiment_dir = study / str(record.get("experiment_dir"))
    request_root = experiment_dir / "trace-defense-v2-requests"
    incomplete = []
    for directory in sorted(request_root.iterdir()):
        attempts = sorted(directory.glob("attempt-*.json"))
        if not attempts or (directory / "result.json").exists():
            continue
        values = [read_object(path, "incomplete request attempt") for path in attempts]
        incomplete.append(
            {
                "request_key": directory.name,
                "attempts": [
                    {
                        "name": path.name,
                        "sha256": sha256_file(path),
                        "stage": value.get("stage"),
                        "status": value.get("status"),
                        "error_type": value.get("error_type"),
                        "error": value.get("error"),
                        "permanent": value.get("permanent"),
                        "has_output": "output" in value,
                        "has_response": "response" in value,
                        "has_result": "result" in value,
                    }
                    for path, value in zip(attempts, values, strict=True)
                ],
            }
        )
    return {
        "task_id": case.task_id,
        "assignment_id": case.assignment_id,
        "record": {
            key: record.get(key)
            for key in (
                "status",
                "error_type",
                "error",
                "failure_category",
                "automatic_recovery_exhausted",
            )
        },
        "incomplete_requests": incomplete,
    }


def inspect_all(
    cases: tuple[RecoveryCase, ...] = CASES,
    *,
    studies: dict[str, Path] | None = None,
) -> list[dict[str, object]]:
    return [
        inspect_case(
            studies[case.task_id] if studies is not None else study_for(case),
            case,
        )
        for case in cases
    ]


def rearm_all(
    cases: tuple[RecoveryCase, ...] = CASES,
    *,
    studies: dict[str, Path] | None = None,
    stamp: str,
) -> list[dict[str, object]]:
    # Validate the complete cross-study scope before the first mutation.
    inspect_all(cases, studies=studies)
    recovered = []
    for case in cases:
        study = studies[case.task_id] if studies is not None else study_for(case)
        with _exclusive_study_lease(study):
            evidence = inspect_case(study, case)
            ledger_path = Path(str(evidence["ledger_path"]))
            ledger = read_object(ledger_path, "study ledger")
            record = next(
                record
                for record in ledger["records"]
                if record["assignment_id"] == case.assignment_id
            )
            archive = (
                study
                / "execution-attempts"
                / case.assignment_id
                / f"openai-billing-{stamp}"
            )
            archive.mkdir(parents=True, exist_ok=False)
            failure_record = archive / "assignment-failure.json"
            write_json_atomic(failure_record, record)
            archived_requests = []
            for request in evidence["requests"]:
                request_dir = Path(str(request["request_dir"]))
                target = archive / request_dir.name
                request_dir.rename(target)
                archived_requests.append(str(target))
            record.update(
                {
                    "automatic_recovery_exhausted": False,
                    "automatic_attempt_count": 0,
                    "next_automatic_action": (
                        "explicit resume after confirmed OpenAI credit restoration"
                    ),
                    "openai_billing_recovery_archive": str(archive),
                }
            )
            write_json_atomic(ledger_path, ledger)
            recovered.append(
                {
                    **evidence,
                    "archive": str(archive),
                    "archived_requests": archived_requests,
                    "assignment_failure": {
                        "path": str(failure_record),
                        "sha256": sha256_file(failure_record),
                    },
                }
            )
    return recovered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("discover", "inspect", "rearm"))
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("OpenAI billing recovery must run through Slurm")
    commit = clean_commit()
    if args.mode == "discover":
        print(
            json.dumps(
                {
                    "source_commit": commit,
                    "cases": [discover_case(study_for(case), case) for case in CASES],
                }
            )
        )
        return
    inspected = inspect_all()
    if args.mode == "inspect":
        print(json.dumps({"source_commit": commit, "cases": inspected}))
        return
    if os.environ.get("RESULT40_OPENAI_CREDITS_CONFIRMED") != "1":
        raise RuntimeError("OpenAI credits must be explicitly confirmed before rearm")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    recovered = rearm_all(stamp=stamp)
    receipt = RUN / f"openai-billing-rearm-{stamp}.json"
    payload = {
        "kind": "result40-gap-improvement-openai-billing-rearm-v2",
        "source_commit": commit,
        "rearmed_assignments": len(recovered),
        "provider_calls": 0,
        "provider_responses_preserved": 0,
        "cases": recovered,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(receipt, payload)
    print(json.dumps({"receipt": str(receipt), **payload}))


if __name__ == "__main__":
    main()
