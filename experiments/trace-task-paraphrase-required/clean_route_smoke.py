"""Minimal same-route Luna smoke for the clean NAS1 execution path."""
from __future__ import annotations
import json, os, re
from pathlib import Path
from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig
root=Path(os.environ["TRACE_CLEAN_SMOKE_ROOT"])
workspace=root/"workspace"; turn=root/"turn-001"
workspace.mkdir(parents=True,exist_ok=True)
(workspace/"answer.txt").write_text("route probe placeholder\n")
(workspace/"trace.md").write_text("route probe placeholder\n")
driver=CodexSdkSessionDriver(AgentRunConfig(provider="codex",model="gpt-5.6-luna",quiet=True,retries=0),contract=BIOMNIBENCH_DA)
rec={"worker_access":"unknown","model":"gpt-5.6-luna","root":str(root)}
try:
    result=driver.start(workspace,"Operational clean-path probe. Write exactly route-ok to answer.txt and state completion in trace.md. Do not install packages, use the network, or modify other files.",turn)
    rec.update(worker_access="available",exit_code=getattr(result,"exit_code",None),outputs=all((workspace/n).is_file() and (workspace/n).stat().st_size>0 for n in ("answer.txt","trace.md")))
except Exception as exc:
    rec.update(worker_access="blocked",error_type=type(exc).__name__,error_message=re.sub(r"(?:sk-[A-Za-z0-9_-]+|Bearer\\s+\\S+)","[redacted]",str(exc))[:500])
finally: driver.close()
(root/"result.json").write_text(json.dumps(rec,indent=2)+"\n")
print(json.dumps({k:rec[k] for k in ("worker_access","model","exit_code","outputs") if k in rec}))
raise SystemExit(0 if rec["worker_access"]=="available" and rec.get("outputs") else 2)
