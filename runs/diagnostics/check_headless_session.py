"""Run a bounded synthetic component check through the real solver session driver."""
import hashlib
from pathlib import Path

from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig

root = Path(__file__).resolve().parent / "headless-plotting-v6d"
workspace = root / "workspace"
fixture = workspace / "validate_plot.py"
before = hashlib.sha256(fixture.read_bytes()).hexdigest()
driver = CodexSdkSessionDriver(
    AgentRunConfig(provider="codex", model="gpt-5.6-luna", quiet=True, retries=0),
    contract=BIOMNIBENCH_DA,
)
try:
    result = driver.start(
        workspace,
        "Synthetic runtime check, not a benchmark task. Execute `python validate_plot.py` "
        "exactly as supplied. Do not edit the script, set environment variables, change "
        "Matplotlib backends, or install packages. Report the actual exit code and output "
        "in trace.md and answer.txt. If the command fails, report failure honestly and stop.",
        root / "turn-001",
    )
    print(result)
finally:
    driver.close()
assert hashlib.sha256(fixture.read_bytes()).hexdigest() == before
assert (workspace / "headless.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
print("HEADLESS_SESSION_IMAGE_CREATED")
