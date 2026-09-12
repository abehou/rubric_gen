"""Run missing native seed blocks in disjoint task lanes; keep every failed block."""
import json
import os
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values
from make_configs import ROOT,BUNDLE,TASKS,RUN
from check_inputs import check
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy

lane=int(sys.argv[1])
if lane not in (0,1):raise ValueError('two disjoint seed lanes: 0 or 1')
for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
    value=os.environ.get(key) or dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(key)
    if value:os.environ[key]=value
jobs=TASKS[lane::2]
# Validate available task/master/selected/development data before any generation.
inputs=[check(t) for t in jobs]
operation=RUN/'operations'/f'seeds-{os.environ["SLURM_JOB_ID"]}'
operation.mkdir(parents=True,exist_ok=False)
record={'job_id':os.environ['SLURM_JOB_ID'],'stage':'seed','lane':lane,'tasks':list(jobs),'inputs':inputs,
        'source':str(ROOT),'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'cpus':int(os.environ['SLURM_CPUS_PER_TASK']),'workers':4,'shared_capacity':policy(),
        'started_at':datetime.now(timezone.utc).isoformat(),'results':[]}
write_json_atomic(operation/'status.json',record)
for task in jobs:
    command=[sys.executable,'-m','rubric_gen.cli','seed','--experiment',str(BUNDLE/'configs'/f'{task}.yaml'),'--max-concurrency','4']
    with (operation/f'{task}.log').open('x') as out:
        code=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,cwd=ROOT).returncode
    record['results'].append({'task':task,'exit_code':code,'log':str(operation/f'{task}.log'),'finished_at':datetime.now(timezone.utc).isoformat()})
    write_json_atomic(operation/'status.json',record)
    print(json.dumps(record['results'][-1]),flush=True)
    # An independent task remains runnable after a native task-local failure.
record['finished_at']=datetime.now(timezone.utc).isoformat()
write_json_atomic(operation/'status.json',record)
raise SystemExit(0 if all(r['exit_code']==0 for r in record['results']) else 1)
