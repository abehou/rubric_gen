"""Existing native input checks and seed-lane dispatch shared by scale shards."""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run

def check_task_inputs(task, *, root, bundle, run, source_pool):
    exp=load_experiment(bundle/'configs'/f'{task}.yaml')
    ref=load_experiment(root/'experiments/trace-attack-defense-v21/result20.yaml')
    assert exp.task_ids==(task,) and len(exp.execution_assignments)==6
    assert exp.replicates==3 and exp.pretreatment_source is None
    for key in ('protocol','solvers','red_team_generator','seed_generator','rubric_paraphrases','randomization','outcome_audit','execution_audit_models'):
        assert exp.payload[key]==ref.payload[key],key
    assert {a.condition_id for a in exp.execution_assignments}=={'full-static','full-red-team-trace'}
    for stage in ('seed','paraphrase','revise','detect'):
        Path(exp.dag[stage]['output_dir']).relative_to(run/task)
    instruction=exp.task_dir(task)/'instruction.md'
    assert instruction.is_file() and instruction.stat().st_size>0
    validate_paraphrase_run(source_pool,exp)
    files=[]
    for index in (0,1):
        p=source_pool/'tasks'/task/f'variant-{index:03d}.json';d=json.loads(p.read_text())
        files.append({'variant_index':index,'path':str(p),'rubric_sha256':d['rubric_sha256'],'master_sha256':d['master_sha256']})
    seed=Path(exp.dag['seed']['output_dir'])
    return {'task':task,'experiment_id':exp.experiment_id,'assignments':6,'instruction_bytes':instruction.stat().st_size,'selected_development_sources':files,'existing_new_seed_manifest':(seed/'manifest.json').is_file()}


def run_seed_lane(lane, *, root, bundle, tasks, run, check_task):
    if lane not in (0,1):raise ValueError('two disjoint seed lanes: 0 or 1')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        value=os.environ.get(key) or dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(key)
        if value:os.environ[key]=value
    jobs=tasks[lane::2]
    # Validate available task/master/selected/development data before any generation.
    inputs=[check_task(t) for t in jobs]
    operation=run/'operations'/f'seeds-{os.environ["SLURM_JOB_ID"]}'
    operation.mkdir(parents=True,exist_ok=False)
    record={'job_id':os.environ['SLURM_JOB_ID'],'stage':'seed','lane':lane,'tasks':list(jobs),'inputs':inputs,
            'source':str(root),'commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'cpus':int(os.environ['SLURM_CPUS_PER_TASK']),'workers':4,'shared_capacity':policy(),
            'started_at':datetime.now(timezone.utc).isoformat(),'results':[]}
    write_json_atomic(operation/'status.json',record)
    for task in jobs:
        command=[sys.executable,'-m','rubric_gen.cli','seed','--experiment',str(bundle/'configs'/f'{task}.yaml'),'--max-concurrency','4']
        with (operation/f'{task}.log').open('x') as out:
            code=subprocess.run(command,stdout=out,stderr=subprocess.STDOUT,cwd=root).returncode
        record['results'].append({'task':task,'exit_code':code,'log':str(operation/f'{task}.log'),'finished_at':datetime.now(timezone.utc).isoformat()})
        write_json_atomic(operation/'status.json',record)
        print(json.dumps(record['results'][-1]),flush=True)
        # An independent task remains runnable after a native task-local failure.
    record['finished_at']=datetime.now(timezone.utc).isoformat()
    write_json_atomic(operation/'status.json',record)
    return (0 if all(r['exit_code']==0 for r in record['results']) else 1)
