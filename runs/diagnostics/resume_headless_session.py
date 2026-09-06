"""Retry the synthetic fixture with the explicitly permitted project interpreter."""
import hashlib
import json
import sys
from pathlib import Path

from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig

root = Path(__file__).resolve().parent / "headless-plotting-v6d"
workspace = root / "workspace"
fixture = workspace / "validate_plot.py"
before = hashlib.sha256(fixture.read_bytes()).hexdigest()
session = json.loads((root / "turn-001/status.json").read_text())["session_id"]
driver = CodexSdkSessionDriver(
    AgentRunConfig(provider="codex", model="gpt-5.6-luna", quiet=True, retries=0),
    contract=BIOMNIBENCH_DA,
)
try:
    result = driver.resume(
        workspace,
        f"Continue the synthetic check using the explicitly permitted project interpreter: "
        f"`{sys.executable} validate_plot.py`. Do not edit validate_plot.py, set any environment "
        "variable, change the plotting backend, or install packages. Preserve the previous "
        "failure in trace.md and append this command's actual result there and in answer.txt. "
        "On failure, report it honestly and stop. Do not modify any other files except those "
        "created by the supplied plotting script.",
        root / "turn-002",
        session,
    )
    print(result)
finally:
    driver.close()
assert hashlib.sha256(fixture.read_bytes()).hexdigest() == before
assert (workspace / "headless.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
print("HEADLESS_SESSION_IMAGE_CREATED")
