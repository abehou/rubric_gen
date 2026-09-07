"""Validate the repaired command environment through the actual Luna driver."""
import hashlib
from pathlib import Path

from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig

root = Path(__file__).resolve().parent / "thread-runtime-v6d"
workspace = root / "workspace"
fixture = workspace / "validate_runtime.py"
before = hashlib.sha256(fixture.read_bytes()).hexdigest()
driver = CodexSdkSessionDriver(
    AgentRunConfig(provider="codex", model="gpt-5.6-luna", quiet=True, retries=0),
    contract=BIOMNIBENCH_DA,
)
try:
    result = driver.start(
        workspace,
        "Synthetic runtime check, not a benchmark task. Run `python validate_runtime.py` "
        "exactly as supplied, with no environment overrides or package installation. "
        "Do not edit the script. Write its actual command, exit code and output to "
        "trace.md and answer.txt. On any failure report it honestly and stop.",
        root / "turn-001",
    )
    print(result)
finally:
    driver.close()
assert hashlib.sha256(fixture.read_bytes()).hexdigest() == before
assert (workspace / "runtime.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
print("RUNTIME_SESSION_IMAGE_CREATED")
