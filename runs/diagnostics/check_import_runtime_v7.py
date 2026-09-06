"""One real synthetic solver check with the explicit current-source launch path."""
import hashlib
from pathlib import Path

from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.models import AgentRunConfig

root = Path(__file__).resolve().parent / 'import-runtime-v7-recovery'
workspace = root / 'workspace'
fixture = workspace / 'validate_runtime.py'
before = hashlib.sha256(fixture.read_bytes()).hexdigest()
driver = CodexSdkSessionDriver(
    AgentRunConfig(provider='codex', model='gpt-5.6-luna', quiet=True, retries=0),
    contract=BIOMNIBENCH_DA,
)
try:
    result = driver.start(
        workspace,
        'Synthetic runtime check, not a benchmark task. Run python validate_runtime.py '
        'exactly as provided, without editing it, overriding environment variables, '
        'or installing packages. Save the actual command, exit code and output to '
        'trace.md and answer.txt. If anything fails, report the failure and stop.',
        root / 'turn-001',
    )
    print(result)
finally:
    driver.close()
assert hashlib.sha256(fixture.read_bytes()).hexdigest() == before
assert (workspace / 'runtime.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
assert 'PROJECT_PYTHON_HEADLESS_THREADS_AND_SECRET_FILTER_PASS' in (workspace / 'answer.txt').read_text()
print('CURRENT_SOURCE_RUNTIME_CHECK_PASSED')
