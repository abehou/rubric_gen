"""Non-provider regressions and a fresh, isolated NFS event-journal smoke."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'runs' / f'telemetry-journal-check-{os.environ["SLURM_JOB_ID"]}'
OUT.mkdir(exist_ok=False)
tests = ['test_runtime_capacity.py', 'test_babel_runtime_evidence.py',
         'test_babel_launcher.py', 'test_architecture.py', 'test_rubric_evolution.py',
         'test_red_team.py', 'test_pretreatment_reuse.py']
paths = sorted((ROOT / 'src').rglob('*.py')) + [ROOT / 'tests' / n for n in tests]
paths += [ROOT / 'tests/conftest.py', Path(__file__)]

def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

before = hashes()
command = [sys.executable, '-m', 'pytest', '-q', *[f'tests/{n}' for n in tests],
           f'--junitxml={OUT / "tests.xml"}']
(OUT / 'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],
    hostname=socket.gethostname(), source_hashes=before, command=command,
    scope='No providers; isolated test pools and fresh NFS telemetry only'), indent=2)+'\n')
with (OUT / 'tests.log').open('w') as log:
    result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    (OUT / 'result.json').write_text(json.dumps(dict(success=False, test_exit=result.returncode))+'\n')
    raise SystemExit(result.returncode)

from rubric_gen.runtime import capacity
coordination = OUT / 'isolated-events'
capacity.policy = lambda: dict(version=1, aggregate_concurrency=60, audit_studies=1,
                              coordination_dir=str(coordination))
started = time.monotonic()
def write(worker):
    for sequence in range(10):
        capacity.emit('journal-smoke', worker=worker, sequence=sequence)
with ThreadPoolExecutor(max_workers=60) as pool:
    list(pool.map(write, range(60)))
elapsed = time.monotonic() - started
files = list(coordination.glob('events-*.jsonl'))
assert len(files) == 1
rows = [json.loads(line) for line in files[0].read_text().splitlines()]
assert len(rows) == 600
assert {(r['worker'], r['sequence']) for r in rows} == {(w, s) for w in range(60) for s in range(10)}
assert before == hashes(), 'source changed during acceptance'
(OUT / 'result.json').write_text(json.dumps(dict(success=True, test_exit=0,
    source_unchanged=True, source_hashes=before, nfs_events=len(rows),
    nfs_writer_threads=60, nfs_elapsed_seconds=elapsed,
    events_sha256=hashlib.sha256(files[0].read_bytes()).hexdigest()), indent=2)+'\n')
