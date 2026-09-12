"""Native missing-only audits per cell; failures do not suppress other tasks."""
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values
from rubric_gen.submission_revision.commands import run_detect
from rubric_gen.submission_revision.experiment import load_experiment
from make_configs import ROOT,BUNDLE,CELLS,TASKS
cell=sys.argv[1]
if cell not in CELLS:raise ValueError('unknown matrix cell')
for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
    value=os.environ.get(key) or dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(key)
    if value:os.environ[key]=value
path=ROOT/'experiments/trace-attack-defense-v21/audit_reuse.py'
spec=importlib.util.spec_from_file_location('queue3_existing_audit_reuse',path)
reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)
reuse.SOURCES=[Path(load_experiment(ROOT/f'experiments/trace-attack-defense-v3/control-v21-compatible/{t}.yaml').dag['detect']['output_dir']) for t in TASKS]
reuse.install()
records=[]
for task in TASKS:
    config=BUNDLE/f'configs/{cell}/{task}.yaml'
    try:
        exp=load_experiment(config)
        ledger=json.loads((Path(exp.dag['revise']['output_dir'])/'study.json').read_text())
        selected=[r for r in ledger['records'] if r['condition_id']==CELLS[cell]]
        if len(selected)!=3 or any(r['status']!='completed' for r in selected):
            raise RuntimeError('selected three-case task cohort incomplete; preserve it for native resume')
        code=run_detect(SimpleNamespace(experiment=str(config),study_dir=None,max_concurrency=32,resume=True))
        if code:raise RuntimeError(f'native detect exited {code}')
        record={'task':task,'status':'completed'}
    except Exception as exc:
        record={'task':task,'status':'incomplete','exception_type':type(exc).__name__,'exception':str(exc)}
    records.append(record)
    out=BUNDLE/f'audit-status-{cell}.json'
    out.write_text(json.dumps({'cell':cell,'job':os.environ.get('SLURM_JOB_ID'),'tasks':records},indent=2)+'\n')
    print(json.dumps(record),flush=True)
raise SystemExit(0 if all(r['status']=='completed' for r in records) else 1)
