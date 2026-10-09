"""Approved Mac revision-only extension, with a durable cost ledger and no audits."""
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading

from dotenv import dotenv_values
from rubric_gen.runtime.process_environment import controlled_process_environment, install_controlled_process_environment
from prepare import HERE, ROOT, OUTPUT

install_controlled_process_environment()
spec=importlib.util.spec_from_file_location('result50_budget_proxy',OUTPUT/'budget_proxy.py')
proxy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
# Restrict this revision-only owner to the approved solver/proposer model.
proxy.PRICES={'gpt-5.6-luna':proxy.PRICES['gpt-5.6-luna']}
local=threading.local()
calculate_cost=proxy.actual_cost


def measured_cost(model,usage):
    cost=calculate_cost(model,usage)
    details=usage.get('input_tokens_details') or {}
    local.usage=dict(model=model,input_tokens=usage['input_tokens'],output_tokens=usage['output_tokens'],
                     cached_tokens=details.get('cached_tokens',0),cache_write_tokens=details.get('cache_write_tokens',0),
                     reasoning_tokens=(usage.get('output_tokens_details') or {}).get('reasoning_tokens',0))
    return cost


proxy.actual_cost=measured_cost


class TrackedLedger(proxy.Ledger):
    def __init__(self,path,limit=100):
        super().__init__(path,limit)
        self.state.setdefault('known_usage_cost_usd',0.)
        self.state.setdefault('unknown_usage_reserved_usd',0.)
        # The base ledger conservatively settles interrupted pending requests.
        unclassified=self.state['spent_usd']-self.state['known_usage_cost_usd']-self.state['unknown_usage_reserved_usd']
        if unclassified>1e-9:self.state['unknown_usage_reserved_usd']+=unclassified
        self.save()
        self.stage='startup'

    def finish(self,key,cost):
        with self.condition:
            reserved=self.state['pending'][key]
            super().finish(key,cost)
            bucket='known_usage_cost_usd' if cost is not None else 'unknown_usage_reserved_usd'
            self.state[bucket]=self.state.get(bucket,0)+(reserved if cost is None else cost)
            self.save()
            event=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),stage=self.stage,
                       reservation_usd=reserved,cost_usd=reserved if cost is None else cost,
                       usage_known=cost is not None,usage=getattr(local,'usage',None) if cost is not None else None)
            with (self.path.parent/'cost-events.jsonl').open('a') as stream:
                stream.write(json.dumps(event)+'\n')
            local.usage=None


def prepare_budget_recovery(invocation, study_path):
    """Preserve stopped evidence and apply the explicitly approved $150 allowance."""
    from rubric_gen.artifacts.serialization import write_json_atomic
    budget_path=OUTPUT/'budget.json'
    original_budget=budget_path.read_bytes()
    budget=json.loads(original_budget)
    if budget['pending'] or budget['limit_usd'] not in (100,150):
        raise RuntimeError('Recovery requires a drained original budget ledger')
    (invocation/'prior-budget.json').write_bytes(original_budget)
    original_study=study_path.read_bytes()
    (invocation/'prior-budget-denial-study.json').write_bytes(original_study)
    study=json.loads(original_study)
    rearmed=[]
    for record in study['records']:
        if (record['status']=='failed' and record.get('automatic_recovery_exhausted')
                and record.get('error_type')=='RubricProposerProviderError'
                and 'Budget relay stopped request: RuntimeError' in record.get('traceback','')):
            record.update(automatic_recovery_exhausted=False,automatic_attempt_count=0,
                          next_automatic_action='explicit resume after authorized local budget extension')
            rearmed.append(record['assignment_id'])
    if rearmed:write_json_atomic(study_path,study)
    budget.update(limit_usd=150,stopped=False)
    write_json_atomic(budget_path,budget)
    return rearmed


def main(*,complete_remaining=False):
    with (OUTPUT/'.run.lock').open('a') as owner:
        fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
        execute(complete_remaining=complete_remaining)


def execute(*,complete_remaining=False):
    key=dotenv_values(ROOT/'.env.local').get('OPENAI_API_KEY')
    if not key or not key.endswith('IfoA') or key.startswith('sk-ant-'):
        raise RuntimeError('Previously confirmed OpenAI credential unavailable')
    sys.path.insert(0,str(OUTPUT/'runtime-source/src'))
    from rubric_gen.submission_revision.experiment import load_experiment
    config=HERE/'extension.yaml'
    e=load_experiment(config)
    assert len(e.assignments)==720
    worker_key='sk-local-budget-'+secrets.token_hex(24)
    env=controlled_process_environment()
    for name in list(env):
        if any(x in name for x in ('API_KEY','ACCESS_TOKEN')) or name in (
                'OPENAI_BASE_URL','OPENAI_API_BASE','OPENAI_ORG_ID','OPENAI_PROJECT_ID',
                'RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY'):
            env.pop(name)
    env.update(OPENAI_API_KEY=worker_key,CODEX_API_KEY=worker_key,
               OPENAI_BASE_URL='http://127.0.0.1:18767/v1',
               RUBRIC_GEN_OPENAI_BUDGET_URL='http://127.0.0.1:18767/v1',
               RUBRIC_GEN_PROJECT_ROOT=str(ROOT),PYTHONPATH=str(OUTPUT/'runtime-source/src'),
               RUBRIC_GEN_RUNTIME_CONFIG=str(HERE/'runtime.json'),RUBRIC_GEN_OPENAI_REASONING_EFFORT='low')
    invocation=OUTPUT/'invocations'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    invocation.mkdir(parents=True,exist_ok=False)
    study_path=Path(e.dag['revise']['output_dir'])/'study.json'
    rearmed=prepare_budget_recovery(invocation,study_path) if complete_remaining else []
    ledger=TrackedLedger(OUTPUT/'budget.json',150 if complete_remaining else 100)
    for path in [Path(__file__),config,HERE/'runtime.json',OUTPUT/'budget_proxy.py']:
        shutil.copy2(path,invocation/path.name)
    receipt=dict(status='starting',pid=os.getpid(),started_utc=datetime.now(timezone.utc).isoformat(),
                 host='local Mac',experiment_id=e.experiment_id,assignments=720,retained_assignments=480,
                 outer_queues=1,assignment_workers=6,aggregate_provider_concurrency=12,
                 internal_fanout=4,audit_workers=0,cpu=os.cpu_count(),memory_gib=24,
                 resource_reservation='none; local process',expected_wall_hours=[3,4] if complete_remaining else [10,14],
                 runtime_exception='User retains Mac; missing-only recovery approximately3–4h' if complete_remaining else 'User retains Mac after disclosure of approximately11h; one shared720-assignment queue',
                 estimate_usd=58.2,planning_range_usd=[50,80],budget_usd=150 if complete_remaining else 100,
                 recovery=complete_remaining,rearmed_budget_denials=rearmed,
                 recovery_additional_cost_range_usd=[15,25] if complete_remaining else None,
                 user_reported_actual_cost_usd=42.10 if complete_remaining else None,
                 source=json.loads((OUTPUT/'preparation.json').read_text()),stages=[])
    def save():
        receipt['budget']=json.loads((OUTPUT/'budget.json').read_text())
        (invocation/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    server=None
    try:
        server=proxy.start_proxy(key,ledger,worker_key,port=18767)
        receipt['status']='running'; save()
        print(str(invocation/'receipt.json'),flush=True)
        for stage in ['seed','paraphrase','revise']:
            ledger.stage=stage
            command=[sys.executable,'-m','rubric_gen.cli',stage,'--experiment',str(config),
                     '--max-concurrency',str(12 if stage=='revise' else 6)]
            if stage=='revise':command+=['--assignment-workers','6','--resume']
            record=dict(stage=stage,status='running',started_utc=datetime.now(timezone.utc).isoformat(),
                        command=command,budget_before=json.loads((OUTPUT/'budget.json').read_text()))
            receipt['stages'].append(record);save()
            print(stage,str(invocation/f'{stage}.log'),flush=True)
            with (invocation/f'{stage}.log').open('w') as stream:
                result=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
            record.update(exit_code=result.returncode,status='completed' if result.returncode==0 else 'failed',
                          ended_utc=datetime.now(timezone.utc).isoformat(),
                          budget_after=json.loads((OUTPUT/'budget.json').read_text()))
            save()
            if result.returncode:raise RuntimeError(f'{stage} incomplete; successful artifacts retained for native resume')
        study=json.loads((Path(e.dag['revise']['output_dir'])/'study.json').read_text())
        assert len(study['records'])==720 and all(r['status']=='completed' for r in study['records'])
        receipt['status']='completed'
    except BaseException:
        receipt['status']='failed'
        raise
    finally:
        if server is not None:server.shutdown();server.server_close()
        receipt['ended_utc']=datetime.now(timezone.utc).isoformat();save()


if __name__=='__main__':
    main()
