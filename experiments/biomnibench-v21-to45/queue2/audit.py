"""Run the native Sol+Opus suite, reusing exact saved control judgments."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values
from rubric_gen.submission_revision.commands import run_detect
from rubric_gen.submission_revision.experiment import load_experiment

ROOT=Path(__file__).resolve().parents[3]
cell=sys.argv[1]
if cell not in {'R1','R2'}:
    raise ValueError('expected R1 or R2')
canonical_tasks=('da-3-4','da-11-1','da-18-1')
tasks=tuple(sys.argv[2:]) or canonical_tasks
if tasks != tuple(t for t in canonical_tasks if t in tasks):
    raise ValueError('audit tasks must be a unique canonical-order subset')
for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
    value=os.environ.get(key) or dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(key)
    if value:
        os.environ[key]=value
# This is the already-reviewed exact current-format import adapter, not a
# new recovery mechanism. Native validation checks each imported judgment.
path=ROOT/'experiments/trace-attack-defense-v21/audit_reuse.py'
spec=importlib.util.spec_from_file_location('queue2_existing_audit_reuse',path)
reuse=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)
reuse.SOURCES=[Path(load_experiment(ROOT/f'experiments/trace-attack-defense-v3/control-v21-compatible/{t}.yaml').dag['detect']['output_dir'])
               for t in ('da-3-4','da-11-1','da-18-1')]
reuse.install()
for task in tasks:
    config=ROOT/f'experiments/biomnibench-v21-to45/queue2/configs/{cell}/{task}.yaml'
    print(json.dumps({'cell':cell,'task':task,'stage':'native_detect','resume':True}),flush=True)
    code=run_detect(SimpleNamespace(experiment=str(config),study_dir=None,max_concurrency=32,resume=True))
    if code:
        raise SystemExit(code)
