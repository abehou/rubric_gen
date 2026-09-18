"""Run a completed local Dev3 through the matched Sol+Opus audit."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace
import uuid

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.commands import run_detect
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--max-concurrency", type=int, default=12)
    parser.add_argument("--expected-assignments", type=int, default=18)
    args = parser.parse_args()

    experiment_path = args.experiment.expanduser()
    runtime_path = args.runtime_config.expanduser()
    receipt_root = args.receipt_root.expanduser()
    for path in (experiment_path, runtime_path):
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeError("local audit inputs must be absolute regular files")
    if not receipt_root.is_absolute() or receipt_root.is_symlink():
        raise RuntimeError("local audit receipt root must be absolute and non-symlinked")
    if not 1 <= args.max_concurrency <= 12:
        raise ValueError("local audit concurrency must be between 1 and 12")
    if args.expected_assignments < 1:
        raise ValueError("expected assignments must be positive")

    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(runtime_path.resolve())
    os.environ.pop("RUBRIC_GEN_OPENAI_REASONING_EFFORT", None)
    runtime = policy()
    if runtime["audit_studies"] != 1:
        raise RuntimeError("local audit studies must remain serialized")

    credentials = dotenv_values(ROOT / ".env.local")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = os.environ.get(name) or credentials.get(name)
        if not value:
            raise RuntimeError(f"configured {name} absent")
        os.environ[name] = str(value)

    experiment = load_experiment(experiment_path)
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError("configured outcome audit panel differs from Sol+Opus")
    if tuple(experiment.payload.get("execution_audit_models", ())) != PANEL:
        raise RuntimeError("configured execution audit panel differs from Sol+Opus")
    study = Path(experiment.dag["revise"]["output_dir"])
    audit = Path(experiment.dag["detect"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text(encoding="utf-8"))
    completed = terminal_records(experiment, ledger)
    if (len(completed) != args.expected_assignments
            or any(row["status"] != "completed" for row in completed)):
        raise RuntimeError(
            "matched audit requires exactly "
            f"{args.expected_assignments} completed assignments"
        )

    invocation = (
        "sol-opus-audit-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    detect_args = SimpleNamespace(
        experiment=str(experiment_path),
        study_dir=None,
        max_concurrency=args.max_concurrency,
        resume=True,
    )
    code = run_detect(detect_args)
    if code:
        raise RuntimeError(f"native matched audit returned {code}")

    receipt = {
        "kind": "local_dev3_matched_sol_opus_audit",
        "invocation": invocation,
        "host": socket.gethostname(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "panel": list(PANEL),
        "openai_reasoning_effort": "none",
        "anthropic_effort": "low",
        "max_concurrency": args.max_concurrency,
        "runtime": runtime,
        "experiment": str(experiment_path),
        "experiment_id": experiment.experiment_id,
        "study": str(study),
        "audit": str(audit),
        "config_sha256": sha256_file(experiment_path),
        "runtime_config_sha256": sha256_file(runtime_path),
        "expected_assignments": args.expected_assignments,
        "completed_assignments": len(completed),
        "resume": "native missing-only",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    owner = receipt_root / "owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "audit-completion.json", receipt)
    write_json_atomic(receipt_root / "sol-opus-audit-completion.json", receipt)
    print(json.dumps({
        "stage": "local_dev3_matched_sol_opus_audit_complete",
        "assignments": len(completed),
        "panel": list(PANEL),
        "max_concurrency": args.max_concurrency,
    }), flush=True)


if __name__ == "__main__":
    main()
