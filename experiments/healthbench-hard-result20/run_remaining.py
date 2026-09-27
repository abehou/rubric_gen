"""Run only the authorized Semi/Score-only Result20 extension on the Mac."""
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
from prepare_remaining import HERE, ROOT, OUTPUT


def main():
    with (OUTPUT / '.run.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute()


def execute():
    config = HERE / 'remaining.yaml'
    e = load_experiment(config)
    assert len(e.assignments) == 240
    assert {c['feedback_policy'] for c in e.payload['conditions']} == {'semi','score_only'}
    assert e.pretreatment_source is not None
    assert (OUTPUT / 'preparation.json').is_file()
    key = dotenv_values(ROOT / '.env.local').get('OPENAI_API_KEY')
    if not key or not key.endswith('IfoA'):
        raise RuntimeError('Confirmed OpenAI credential unavailable')
    ledger = Ledger(OUTPUT / 'budget.json', 30.)
    env = controlled_process_environment()
    for name in list(env):
        if any(x in name for x in ('API_KEY','ACCESS_TOKEN')) or name in (
            'OPENAI_BASE_URL','OPENAI_API_BASE','OPENAI_ORG_ID','OPENAI_PROJECT_ID',
            'RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY'):
            env.pop(name)
    worker_key = 'sk-local-budget-' + secrets.token_hex(24)
    env.update(OPENAI_API_KEY=worker_key, CODEX_API_KEY=worker_key,
        OPENAI_BASE_URL='http://127.0.0.1:18765/v1',
        RUBRIC_GEN_OPENAI_BUDGET_URL='http://127.0.0.1:18765/v1',
        RUBRIC_GEN_PROJECT_ROOT=str(ROOT),
        PYTHONPATH=str(OUTPUT / 'runtime-source/src'),
        RUBRIC_GEN_RUNTIME_CONFIG=str(HERE / 'runtime.json'))
    invocation = OUTPUT / 'invocations' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    invocation.mkdir(parents=True)
    for name in ('run_remaining.py','remaining.yaml','runtime.json','budget_proxy.py'):
        shutil.copy2(HERE / name, invocation / name)
    receipt = dict(status='running', pid=os.getpid(), host='local Mac',
        started_utc=datetime.now(timezone.utc).isoformat(), experiment_id=e.experiment_id,
        assignments=240, outer_shards=1, assignment_workers=6,
        provider_concurrency=12, internal_fanout=4, audit_concurrency=12,
        cpu=os.cpu_count(), memory_gib=24, resource_reservation='none; local process',
        expected_wall_minutes=[180,300], estimate_usd=[22,30], budget_usd=30,
        runtime_exception='Preserve user-requested Mac execution; saved Result20 throughput exceeds two hours',
        source_dir=str(OUTPUT/'runtime-source'),
        scientific_scope='Original Result20 solver/RTT prompts; new RH guidance; Semi/Score-only only',
        reused_stages=['seed','paraphrase','pretreatment'], stages=[])
    def save():
        (invocation/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    save()
    server = None
    try:
        server = start_proxy(key, ledger, worker_key)
        for stage in ('revise','detect'):
            command = [sys.executable,'-m','rubric_gen.cli',stage,'--experiment',str(config),
                '--max-concurrency','12','--resume']
            if stage == 'revise':
                command += ['--assignment-workers','6']
            else:
                command += ['--study-dir', e.dag['revise']['output_dir']]
            record = dict(stage=stage, status='running', command=command,
                started_utc=datetime.now(timezone.utc).isoformat())
            receipt['stages'].append(record); save()
            with (invocation/f'{stage}.log').open('w') as stream:
                result = subprocess.run(command,cwd=ROOT,env={**env,
                    'RUBRIC_GEN_OPENAI_REASONING_EFFORT':'high' if stage=='detect' else 'low'},
                    stdout=stream,stderr=subprocess.STDOUT)
            record.update(exit_code=result.returncode,
                ended_utc=datetime.now(timezone.utc).isoformat(),
                status='completed' if result.returncode==0 else 'failed')
            save()
            if result.returncode:
                raise RuntimeError(f'{stage} incomplete; preserved successful calls for native resume')
        receipt['status']='completed'
    except BaseException:
        receipt['status']='failed'
        raise
    finally:
        if server is not None:
            server.shutdown(); server.server_close()
        receipt.update(ended_utc=datetime.now(timezone.utc).isoformat(),
            budget=json.loads((OUTPUT/'budget.json').read_text()))
        save()


if __name__ == '__main__':
    main()
