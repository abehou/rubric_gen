"""One bounded real Codex request to verify the current scientific-worker route.

This is an operational diagnostic only; it is not a BioMNIBench assignment and
its response is not used by any scientific run.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig


root = Path(os.environ["TRACE_ROUTE_ROOT"])
workspace = root / "workspace"
turn_dir = root / "turn-001"
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "answer.txt").write_text("route probe placeholder\n", encoding="utf-8")
(workspace / "trace.md").write_text("route probe placeholder\n", encoding="utf-8")

record: dict[str, object] = {
    "worker_access": "unknown",
    "auth_source_configured": bool(os.environ.get("CODEX_HOME")),
    "model": "gpt-5.6-luna",
}
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
    )
    record.update({
        "worker_access": "available",
        "turn_exit_code": getattr(result, "exit_code", None),
        "required_outputs_present": all(
            (workspace / name).is_file() and (workspace / name).stat().st_size > 0
            for name in ("answer.txt", "trace.md")
        ),
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

(root / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps({k: record[k] for k in record if k not in {"error_message"}}, sort_keys=True))
if record["worker_access"] != "available":
    raise SystemExit(2)
