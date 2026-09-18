"""Provider-free saved-case and mask validation for provenance dropout."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.rubric_dropout import (
    PROVENANCE_DROPOUT_VERSION,
)


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN_ROOT = ROOT / "runs/trace-v21-execution-verified-provenance-dropout-local-mac"
OLD_RUNNER = ROOT / "experiments/trace-v21-execution-verified-dropout/run_local.py"
PROVENANCE_RECEIPT = (
    ROOT
    / "runs/trace-v21-execution-verified-provenance-high-proposer-local-mac/"
    "saved-case-behavior/validation.json"
)


def _old_runner():
    spec = importlib.util.spec_from_file_location(
        "execution_verified_saved_case_source", OLD_RUNNER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the saved-case validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    old_cases = _old_runner()._validate_saved_cases()
    if not old_cases.get("ready") or not all(old_cases.get("checks", {}).values()):
        raise RuntimeError("the four execution-verified saved cases are not valid")
    if PROVENANCE_RECEIPT.is_symlink() or not PROVENANCE_RECEIPT.is_file():
        raise RuntimeError("the provenance saved-case receipt is missing")
    provenance = json.loads(PROVENANCE_RECEIPT.read_text(encoding="utf-8"))
    if provenance.get("status") != "passed":
        raise RuntimeError("the provenance behavior checks are not valid")

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_execution_verified_dropout.py",
        "-k",
        (
            "provenance_dropout or "
            "protected_issue_is_delivered_completely_and_persisted or "
            "honest_downgrade_is_not_followed_by_another_reminder"
        ),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError("focused dropout checks failed:\n" + completed.stdout)

    receipt = {
        "kind": "provenance-high-proposer-dropout-saved-case-validation-v1",
        "trace_version": PROVENANCE_DROPOUT_VERSION,
        "status": "passed",
        "provider_calls": 0,
        "rates": [0.3, 0.5],
        "arms": ["full", "user_simulator"],
        "execution_verified_cases": old_cases,
        "provenance_cases": {
            "path": str(PROVENANCE_RECEIPT.resolve()),
            "sha256": sha256_file(PROVENANCE_RECEIPT),
            "passed_cases": provenance.get("passed_cases"),
        },
        "focused_test_command": command,
        "focused_test_output": completed.stdout,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    destination = RUN_ROOT / "saved-case-validation/validation.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(destination, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
