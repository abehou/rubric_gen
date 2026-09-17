"""One bounded real Codex request to verify the current scientific-worker route.

This is an operational diagnostic only; it is not a BioMNIBench assignment and
its response is not used by any scientific run.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.capacity import policy
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig


root = Path(os.environ["TRACE_ROUTE_ROOT"])
workspace = root / "workspace"
turn_dir = root / "turn-001"
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "answer.txt").write_text("route probe placeholder\n", encoding="utf-8")
(workspace / "trace.md").write_text("route probe placeholder\n", encoding="utf-8")

runtime = policy()
record: dict[str, object] = {
    "worker_access": "unknown",
    "auth_source_configured": bool(os.environ.get("CODEX_HOME")),
    "model": "gpt-5.6-luna",
    "runtime": runtime,
    "slurm_job_id_present": bool(os.environ.get("SLURM_JOB_ID")),
}
session: dict[str, str] = {}


def persist_session(session_id: str) -> None:
    session["session_id"] = session_id
    write_json_atomic(root / "session.json", session)


driver = CodexSdkSessionDriver(
    AgentRunConfig(provider="codex", model="gpt-5.6-luna", quiet=True, retries=0),
    contract=BIOMNIBENCH_DA,
)
try:
    result = driver.start(
        workspace,
        "Operational route probe, not a benchmark task. Write exactly `route-ok` "
        "to answer.txt and state that the probe completed in trace.md. Do not "
        "install packages, use the network, or modify any other files.",
        turn_dir,
        on_session_id=persist_session,
    )
    saved_session = json.loads((root / "session.json").read_text(encoding="utf-8"))
    answer = (workspace / "answer.txt").read_text(encoding="utf-8").strip()
    trace = (workspace / "trace.md").read_text(encoding="utf-8")
    coordination = Path(str(runtime["coordination_dir"]))
    record.update({
        "worker_access": "available",
        "turn_exit_code": getattr(result, "exit_code", None),
        "required_outputs_present": answer == "route-ok" and "completed" in trace.lower(),
        "output_sha256": {
            name: sha256_file(workspace / name) for name in ("answer.txt", "trace.md")
        },
        "resume_state_readable": bool(saved_session.get("session_id")),
        "runtime_coordination_present": any(coordination.glob("events-*.jsonl")),
    })
except Exception as exc:  # Operational classification; never expose secrets.
    message = re.sub(r"(?:sk-[A-Za-z0-9_-]+|Bearer\s+\S+)", "[redacted]", str(exc))
    record.update({
        "worker_access": "blocked",
        "error_type": type(exc).__name__,
        "error_message": message[:500],
    })
finally:
    driver.close()

write_json_atomic(root / "result.json", record)
print(json.dumps({k: record[k] for k in record if k not in {"error_message"}}, sort_keys=True))
if (record["worker_access"] != "available"
        or not record.get("required_outputs_present")
        or not record.get("resume_state_readable")
        or not record.get("runtime_coordination_present")):
    raise SystemExit(2)
