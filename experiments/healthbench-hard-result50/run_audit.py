"""Complete only the approved new30 Result50 audits, with separate accounting."""
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
spec = importlib.util.spec_from_file_location('result50_audit_proxy', OUTPUT/'budget_proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
proxy.PRICES = {m: proxy.PRICES[m] for m in ('gpt-6-luna', 'gpt-6-sol')}
local = threading.local()
calculate_cost = proxy.actual_cost


def measured_cost(model, usage):
    cost = calculate_cost(model, usage)
    local.usage = {'model': model, **usage}
    return cost


proxy.actual_cost = measured_cost


class TrackedLedger(proxy.Ledger):
    def __init__(self, path):
        super().__init__(path, 50.)
        self.state.setdefault('known_usage_cost_usd', 0.)
        self.state.setdefault('unknown_usage_reserved_usd', 0.)
        unclassified = self.state['spent_usd'] - self.state['known_usage_cost_usd'] - self.state['unknown_usage_reserved_usd']
        if unclassified > 1e-9:
            self.state['unknown_usage_reserved_usd'] += unclassified
        self.save()

    def finish(self, key, cost):
        with self.condition:
            reserved = self.state['pending'][key]
            super().finish(key, cost)
            bucket = 'known_usage_cost_usd' if cost is not None else 'unknown_usage_reserved_usd'
            self.state[bucket] += reserved if cost is None else cost
            self.save()
            event = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(), stage='detect',
                         reservation_usd=reserved, cost_usd=reserved if cost is None else cost,
                         usage_known=cost is not None,
                         usage=getattr(local, 'usage', None) if cost is not None else None)
            with (self.path.parent/'cost-events.jsonl').open('a') as stream:
                stream.write(json.dumps(event)+'\n')
            local.usage = None


def main():
    with (OUTPUT/'.run.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute()


def execute():
    key = dotenv_values(ROOT/'.env.local').get('OPENAI_API_KEY')
    if not key or not key.endswith('IfoA'):
        raise RuntimeError('Previously authorized OpenAI credential unavailable')
    sys.path.insert(0, str(OUTPUT/'runtime-source/src'))
    from rubric_gen.submission_revision.experiment import load_experiment
    config = HERE/'extension.yaml'
    experiment = load_experiment(config)
    study_dir = Path(experiment.dag['revise']['output_dir'])
    study = json.loads((study_dir/'study.json').read_text())
    assert len(study['records']) == 720 and all(r['status'] == 'completed' for r in study['records'])
    assert experiment.outcome_audit['models'] == ['gpt-6-luna']
    assert experiment.outcome_audit['rubric_free_models'] == ['gpt-6-sol']
    audit_run = OUTPUT/'audit-run'
    audit_run.mkdir(exist_ok=True)
    invocation = audit_run/'invocations'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    invocation.mkdir(parents=True, exist_ok=False)
    for path in (Path(__file__), config, HERE/'runtime.json', OUTPUT/'budget_proxy.py'):
        shutil.copy2(path, invocation/path.name)
    recovery = None
    audit_dir = OUTPUT/'audits'/experiment.experiment_id
    if (audit_dir/'rubric_score/summary.json').exists():
        summary = json.loads((audit_dir/'rubric_score/summary.json').read_text())
        failed = {r['judgment_key'] for r in summary['judge_failures']}
        expected = {'641b35dd65a0533b51484fe32c2e638f', '76ccde030f7aa0e1535a19176d0082b5',
                    'e4244256f27c815b06eba62c84addf22', 'ec40bcf78082770cdfbb5141dc911521'}
        if failed:
            assert failed == expected, 'Unexpected missing judgments; inspect before dispatch'
            manifest = json.loads((audit_dir/'rubric_score/manifest.json').read_text())
            jobs = manifest['predispatch_plan']['jobs']
            missing = [j for j in jobs if j['semantic_key'] in failed]
            assert len(missing) == 4
            fields = ('rubric_sha256', 'review_input_sha256', 'answer_input_sha256')
            allowances = [{**{f:j[f] for f in fields}, 'max_output_tokens':8192} for j in missing]
            assert sum(any(all(j[f] == a[f] for f in fields) for a in allowances) for j in jobs) == 4
            recovery = invocation/'output-allowances.json'
            recovery.write_text(json.dumps(allowances, indent=2)+'\n')
            shutil.copy2(HERE/'audit_recovery_worker.py', invocation/'audit_recovery_worker.py')
            archive = invocation/'prior-audit'
            archive.mkdir()
            for path in audit_dir.rglob('summary.json'):
                destination = archive/path.relative_to(audit_dir)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            shutil.copy2(audit_run/'budget.json', archive/'budget.json')
            # Native retry counters persist. Archive only these confirmed failed
            # requests so the repaired output allowance can receive fresh attempts.
            for judgment in failed:
                artifact = audit_dir/'rubric_score/artifacts'/judgment
                assert not list(artifact.rglob('usage.json'))
                attempts = list(artifact.rglob('*.attempts'))
                assert len(attempts) == 1
                states = list(attempts[0].glob('attempt-*.json'))
                assert len(states) == 3 and all('max_output_tokens' in p.read_text() for p in states)
                targets = [attempts[0], *attempts[0].parent.glob('failed-attempt-*.json')]
                for path in targets:
                    destination = archive/path.relative_to(audit_dir)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    path.rename(destination)
            chunk = next((audit_dir/'direct_full_trajectory').glob(
                'evaluations/*/cases/revision-000463/gpt-6-luna/chunk-001'))
            assert not (chunk.parent/'score.json').exists()
            raw = chunk/'attempt-001.json'
            failure = json.loads(raw.read_text())
            assert failure['error_type'] == 'InternalServerError' and '520' in failure['error']
            assert not failure.get('generation')
            destination = archive/raw.relative_to(audit_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            raw.rename(destination)
    env = controlled_process_environment()
    for name in list(env):
        if any(x in name for x in ('API_KEY', 'ACCESS_TOKEN')) or name in (
            'OPENAI_BASE_URL', 'OPENAI_API_BASE', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID',
            'RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY'):
            env.pop(name)
    worker_key = 'sk-local-budget-' + secrets.token_hex(24)
    env.update(OPENAI_API_KEY=worker_key, CODEX_API_KEY=worker_key,
               OPENAI_BASE_URL='http://127.0.0.1:18768/v1',
               RUBRIC_GEN_OPENAI_BUDGET_URL='http://127.0.0.1:18768/v1',
               RUBRIC_GEN_PROJECT_ROOT=str(ROOT), PYTHONPATH=str(OUTPUT/'runtime-source/src'),
               RUBRIC_GEN_RUNTIME_CONFIG=str(HERE/'runtime.json'),
               RUBRIC_GEN_OPENAI_REASONING_EFFORT='high')
    ledger = TrackedLedger(audit_run/'budget.json')
    command = [sys.executable, '-m', 'rubric_gen.cli', 'detect', '--experiment', str(config),
               '--study-dir', str(study_dir), '--max-concurrency', '12', '--resume']
    if recovery:
        command = [sys.executable, str(invocation/'audit_recovery_worker.py'), str(recovery), *command[3:]]
    receipt = dict(status='starting', pid=os.getpid(), started_utc=datetime.now(timezone.utc).isoformat(),
                   host='local Mac', experiment_id=experiment.experiment_id, assignments=720,
                   retained_assignments_untouched=480, command=command, source_dir=str(OUTPUT/'runtime-source'),
                   outer_queues=1, assignment_workers=0, aggregate_provider_concurrency=12,
                   internal_fanout=1, audit_workers=12, cpu=os.cpu_count(), memory_gib=24,
                   expected_wall_minutes=[90, 150], estimate_usd=25, planning_range_usd=[20, 30],
                   conservative_ledger_limit_usd=50, models={'rubric_RH':'gpt-6-luna high', 'A_pairwise':'gpt-6-sol high'},
                   runtime_exception='Retain approved Mac execution; historical 240-assignment audit40.8min scales to approximately122min',
                   scope='New30 only; original Result20 scoring and corrected answer-only RH guidance; no solver or old20 reruns')
    if recovery:
        receipt.update(expected_wall_minutes=[5,15], incremental_estimate_usd=0.10,
                       output_recovery=str(recovery), missing_only={'rubric':4, 'full_trajectory_RH':1})
    def save():
        receipt['budget'] = json.loads((audit_run/'budget.json').read_text())
        (invocation/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    server = None
    save()
    try:
        server = proxy.start_proxy(key, ledger, worker_key, port=18768)
        receipt['status'] = 'running'; save()
        print(invocation/'receipt.json', flush=True)
        with (invocation/'detect.log').open('w') as stream:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
        receipt['exit_code'] = result.returncode
        if result.returncode:
            raise RuntimeError('Audit incomplete; preserve successful calls for native missing-only resume')
        receipt['status'] = 'completed'
    except BaseException:
        receipt['status'] = 'failed'
        raise
    finally:
        if server is not None:
            server.shutdown(); server.server_close()
        receipt['ended_utc'] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == '__main__':
    main()
