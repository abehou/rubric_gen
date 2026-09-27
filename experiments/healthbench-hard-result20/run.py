"""Approved $30 HealthBench challenge20 on the local Mac shared queue."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

from dotenv import dotenv_values
from rubric_gen.runtime.process_environment import controlled_process_environment
from rubric_gen.submission_revision.experiment import load_experiment
from budget_proxy import Ledger, start_proxy
from prepare import PERSISTENT

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main(*, audit_only=False, output_recovery=False):
    PERSISTENT.mkdir(parents=True, exist_ok=True)
    # One owner must hold the lock before loading/recovering pending charges.
    with (PERSISTENT / '.run.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(audit_only=audit_only, output_recovery=output_recovery)


def run(*, audit_only=False, output_recovery=False):
    key = dotenv_values(ROOT / '.env.local').get('OPENAI_API_KEY')
    if not key or not key.endswith('IfoA') or key.startswith('sk-ant-'):
        raise RuntimeError('Confirmed OpenAI credential unavailable')
    PERSISTENT.mkdir(parents=True, exist_ok=True)
    tasks = PERSISTENT / 'tasks'
    if not tasks.exists():
        shutil.copytree(ROOT / 'data/healthbench-hard/challenge20-20260926', tasks)
    configs = [HERE / 'local.yaml']
    experiments = [load_experiment(p) for p in configs]
    assert sum(len(e.assignments) for e in experiments) == 240
    if audit_only:
        study = json.loads((Path(experiments[0].dag['revise']['output_dir'])/'study.json').read_text())
        if len(study['records']) != 240 or any(r['status'] != 'completed' for r in study['records']):
            raise RuntimeError('Audit-only recovery requires all 240 completed solver assignments')
    recovery = None
    if output_recovery:
        if not audit_only:
            raise ValueError('Output recovery is audit-only')
        audit = PERSISTENT/'audits'/experiments[0].experiment_id/'rubric_score'
        prior = json.loads((audit/'summary.json').read_text())
        missing = [j for j in prior['predispatch_plan']['jobs']
                   if not (audit/'records'/f"{j['semantic_key']}.json").exists()]
        if len(missing) != 1 or missing[0]['semantic_key'] != 'e908fb6dcb73a6a15497801ca9a95075':
            raise RuntimeError('This authorization covers only the single recorded missing judgment')
        recovery = {k:missing[0][k] for k in ('rubric_sha256','review_input_sha256','answer_input_sha256')}
        recovery['max_output_tokens'] = 8192
    ledger = Ledger(PERSISTENT / 'budget.json', 30., allow_overrun=audit_only)
    worker_key = 'sk-local-budget-' + secrets.token_hex(24)
    server = start_proxy(key, ledger, worker_key)
    env = controlled_process_environment()
    for name in list(env):
        if any(x in name for x in ('API_KEY','ACCESS_TOKEN')) or name in (
            'OPENAI_BASE_URL','OPENAI_API_BASE','OPENAI_ORG_ID','OPENAI_PROJECT_ID'):
            env.pop(name)
    env.update(OPENAI_API_KEY=worker_key, CODEX_API_KEY=worker_key,
               OPENAI_BASE_URL='http://127.0.0.1:18765/v1',
               RUBRIC_GEN_OPENAI_BUDGET_URL='http://127.0.0.1:18765/v1',
               PYTHONPATH=str(ROOT/'src'),
               RUBRIC_GEN_RUNTIME_CONFIG=str(HERE/'runtime.json'))
    env.pop('RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY', None)
    if recovery:
        env['RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY'] = json.dumps(recovery)
    receipt_dir = PERSISTENT / 'invocations' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    receipt_dir.mkdir(parents=True)
    if audit_only:
        # Preserve the terminal failure summaries before native resume updates them.
        shutil.copytree(PERSISTENT/'audits'/experiments[0].experiment_id, receipt_dir/'prior-audit')
    shutil.copy2(ROOT/'output/healthbench-result20-preparation/source.tar.gz', receipt_dir/'source.tar.gz')
    receipt = {'status':'running','pid':os.getpid(),'slurm_job_id':os.getenv('SLURM_JOB_ID'),
               'started_utc':datetime.now(timezone.utc).isoformat(),'assignment_count':240,
               'host':'local Mac','outer_shards':1,'assignment_workers_per_shard':0 if audit_only else 6,'aggregate_concurrency':12,
               'internal_fanout':1 if audit_only else 4,'audit_concurrency_total':1 if recovery else 12,'cpu':os.cpu_count(),'memory_gib':24,
               'resource_reservation':'local process; no scheduler reservation',
               'runtime_exception':'User explicitly selected Mac after disclosure of approximately five hours',
               'expected_wall_minutes':[1,5] if recovery else ([60,90] if audit_only else [240,360]),
               'output_recovery':recovery,
               'budget_usd':None if audit_only else 30,'original_budget_usd':30,
               'budget_policy':'User authorized completion of this audit even above $30' if audit_only else 'hard ceiling',
               'scope':'audit-only native resume' if audit_only else 'full workflow',
               'key_suffix':'IfoA',
               'source':json.loads((HERE/'source-receipt.json').read_text()),
               'experiments':[e.experiment_id for e in experiments],'stage_waves':[]}
    def save():
        (receipt_dir/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    def run_stage(index, stage):
        experiment = experiments[index]
        workers = 1 if recovery else (12 if stage in ('revise','detect') else 6)
        command = [sys.executable,'-m','rubric_gen.cli',stage,'--experiment',str(configs[index]),
                   '--max-concurrency',str(workers)]
        if stage in ('revise','detect'): command += ['--resume']
        if stage == 'revise': command += ['--assignment-workers','6']
        if stage == 'detect': command += ['--study-dir',experiment.dag['revise']['output_dir']]
        effort = 'high' if stage == 'detect' else 'low'
        record = {'shard':index+1,'stage':stage,'command':command,'effort':effort,'status':'running'}
        log = receipt_dir/f'{stage}-shard-{index+1}.log'
        print(f'{stage} shard{index+1}: {log}',flush=True)
        with log.open('w') as stream:
            process = subprocess.run(command,cwd=ROOT,
                                     env={**env,'RUBRIC_GEN_OPENAI_REASONING_EFFORT':effort},
                                     stdout=stream,stderr=subprocess.STDOUT)
        record.update(exit_code=process.returncode,status='completed' if process.returncode==0 else 'failed')
        return record
    try:
        # One shared 240-assignment queue keeps six workers busy without
        # serializing independent task shards or stranding per-shard capacity.
        for stage in (('detect',) if audit_only else ('seed','paraphrase','revise','detect')):
            wave = {'stage':stage,'status':'running','results':[]}
            receipt['stage_waves'].append(wave); save()
            record = run_stage(0,stage)
            wave['results'].append(record); save()
            print(json.dumps(record),flush=True)
            if any(r['exit_code'] for r in wave['results']):
                wave['status']='failed'; receipt['status']='failed'; save()
                raise RuntimeError(f'{stage} incomplete; preserved native outputs for resume')
            wave['status']='completed'; save()
        receipt['status']='completed'
    except BaseException:
        receipt['status']='failed'
        raise
    finally:
        receipt['ended_utc']=datetime.now(timezone.utc).isoformat()
        receipt['budget']=json.loads((PERSISTENT/'budget.json').read_text())
        save(); server.shutdown()


if __name__ == '__main__':
    main()
