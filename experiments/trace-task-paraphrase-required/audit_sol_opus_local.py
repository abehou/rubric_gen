"""Run the matched Sol+Opus audit for the completed local Dev3 candidate."""
from __future__ import annotations

import argparse
import copy
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
from rubric_gen.runtime.audit_execution import audit_output_owner
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.commands import _run_detect_owned
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import Experiment, load_experiment


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--receipt-root", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args()
    inputs = (args.experiment, args.runtime_config, args.path_map)
    if any(not p.is_absolute() or p.is_symlink() or not p.is_file() for p in inputs):
        raise RuntimeError("local audit inputs must be absolute regular files")
    for path in (args.receipt_root, args.output_root):
        if not path.is_absolute() or path.is_symlink():
            raise RuntimeError("local audit output paths must be absolute and non-symlinked")
    if not 1 <= args.max_concurrency <= 8:
        raise ValueError("local audit concurrency must be between 1 and 8")
    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(args.path_map.resolve())
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(args.runtime_config.resolve())
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
    invocation = (
        "sol-opus-audit-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    source_experiment = load_experiment(args.experiment)
    if tuple(source_experiment.payload["outcome_audit"]["models"]) != (
        "gpt-5.6-sol", "claude-opus-5", "gemini-3.8-flash"
    ):
        raise RuntimeError("source audit panel differs from the frozen Dev3 config")
    payload = copy.deepcopy(source_experiment.payload)
    payload["execution_audit_models"] = list(PANEL)
    payload["dag"]["detect"]["output_dir"] = str(args.output_root)
    experiment = Experiment(source_experiment.path, payload)
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError("matched audit execution view differs from Sol+Opus")
    study = Path(experiment.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text(encoding="utf-8"))
    completed = terminal_records(experiment, ledger)
    if len(completed) != 18 or any(row["status"] != "completed" for row in completed):
        raise RuntimeError("matched audit requires exactly 18 completed assignments")
    detect_args = SimpleNamespace(max_concurrency=args.max_concurrency, resume=True)
    with audit_output_owner(args.output_root):
        code = _run_detect_owned(
            detect_args,
            experiment,
            study,
            Path(experiment.dag["paraphrase"]["output_dir"]),
            args.output_root,
        )
    if code:
        raise RuntimeError(f"native matched audit returned {code}")
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    receipt = {
        "kind": "candidate_dev3_matched_sol_opus_audit",
        "invocation": invocation,
        "host": socket.gethostname(),
        "commit": commit,
        "panel": list(PANEL),
        "openai_reasoning_effort": "none",
        "anthropic_effort": "low",
        "runtime": runtime,
        "experiment": str(args.experiment),
        "experiment_id": experiment.experiment_id,
        "study": str(study),
        "audit": str(args.output_root),
        "config_sha256": sha256_file(args.experiment),
        "completed_assignments": len(completed),
        "resume": "native missing-only",
        "time": datetime.now(timezone.utc).isoformat(),
    }
    owner = args.receipt_root / "owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "audit-completion.json", receipt)
    write_json_atomic(args.receipt_root / "sol-opus-audit-completion.json", receipt)
    print(json.dumps({
        "stage": "candidate_dev3_matched_sol_opus_audit_complete",
        "assignments": len(completed),
        "panel": list(PANEL),
    }), flush=True)


if __name__ == "__main__":
    main()
