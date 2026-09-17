"""Run the alternate Luna xhigh audit for the completed local candidate."""
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
PANEL = ("gpt-5.6-luna",)
REASONING_EFFORT = "xhigh"
RETRYABLE_EMPTY_RESPONSE = "OpenAI returned an empty response"


def _enable_preserving_empty_response_recovery() -> None:
    """Treat one persisted empty response as retryable without rewriting it."""

    from rubric_gen.submission_revision.evaluation import score_execution

    original_read = score_execution.read_json_object
    original_category = score_execution.failure_category

    def read_with_recovery(path: Path, expected: str) -> dict:
        value = original_read(path, expected)
        if (
            expected == "rubric-free attempt"
            and value.get("generation") is None
            and value.get("category") == "structural"
            and value.get("error") == RETRYABLE_EMPTY_RESPONSE
        ):
            return {**value, "category": "transient_provider"}
        return value

    def classify_with_recovery(error: BaseException) -> str:
        if str(error) == RETRYABLE_EMPTY_RESPONSE:
            return "transient_provider"
        return original_category(error)

    score_execution.read_json_object = read_with_recovery
    score_execution.failure_category = classify_with_recovery


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args()
    config_path = args.experiment.expanduser()
    runtime_config = args.runtime_config.expanduser()
    receipt_root = args.receipt_root.expanduser()
    path_map = args.path_map.expanduser()
    if (not config_path.is_absolute() or config_path.is_symlink() or not config_path.is_file()
            or not runtime_config.is_absolute() or runtime_config.is_symlink()
            or not runtime_config.is_file() or not receipt_root.is_absolute()
            or receipt_root.is_symlink() or not path_map.is_absolute()
            or path_map.is_symlink() or not path_map.is_file()):
        raise RuntimeError("local audit paths must be absolute and non-symlinked")
    if not 1 <= args.max_concurrency <= 8:
        raise ValueError("first local audit concurrency must be between 1 and 8")
    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(path_map.resolve())
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(runtime_config.resolve())
    runtime = policy()
    if runtime["audit_studies"] != 1:
        raise RuntimeError("local audit studies must remain serialized")
    credentials = dotenv_values(ROOT / ".env.local")
    key = os.environ.get("OPENAI_API_KEY") or credentials.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("configured OPENAI_API_KEY absent")
    os.environ["OPENAI_API_KEY"] = str(key)
    os.environ["RUBRIC_GEN_OPENAI_REASONING_EFFORT"] = REASONING_EFFORT
    _enable_preserving_empty_response_recovery()

    invocation = (
        "luna-xhigh-audit-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    experiment = load_experiment(config_path)
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError(f"unexpected configured audit panel in {config_path}")
    study = Path(experiment.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text(encoding="utf-8"))
    completed = terminal_records(experiment, ledger)
    if len(completed) != 18 or any(row["status"] != "completed" for row in completed):
        raise RuntimeError(f"audit requires 18 completed assignments: {config_path}")
    detect_args = SimpleNamespace(
        experiment=str(config_path),
        study_dir=None,
        max_concurrency=args.max_concurrency,
        resume=True,
    )
    code = run_detect(detect_args)
    if code:
        raise RuntimeError(f"native Luna xhigh audit returned {code} for {config_path}")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    receipt = {
        "kind": "candidate_dev3_luna_xhigh_audit",
        "invocation": invocation,
        "host": socket.gethostname(),
        "commit": commit,
        "panel": list(PANEL),
        "openai_reasoning_effort": REASONING_EFFORT,
        "runtime": runtime,
        "experiment": str(config_path),
        "experiment_id": experiment.experiment_id,
        "study": str(study),
        "audit": str(experiment.dag["detect"]["output_dir"]),
        "config_sha256": sha256_file(config_path),
        "completed_assignments": len(completed),
        "resume": "native missing-only",
        "sol_opus_reexecuted": False,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    owner = receipt_root / "owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "audit-completion.json", receipt)
    write_json_atomic(receipt_root / "luna-xhigh-audit-completion.json", receipt)
    print(json.dumps({
        "stage": "candidate_dev3_luna_xhigh_audit_complete",
        "assignments": len(completed),
        "panel": list(PANEL),
    }), flush=True)


if __name__ == "__main__":
    main()
