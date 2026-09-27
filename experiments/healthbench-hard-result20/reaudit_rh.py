"""Prepared RH-only re-audit; execute only after the user approves its $3 budget.

Uses saved solver evidence and the existing native detector. No seed, revision,
rubric-score, absolute-score, or pairwise stage is invoked. Old audits stay intact.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
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
from rubric_gen.runtime.audit_execution import AuditExecutor, audit_owner
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.direct import DirectDetectionConfig, prepare_direct_detection
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources
from budget_proxy import Ledger, start_proxy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / 'runs/healthbench-hard-challenge20-local-20260926'
OUTPUT = RUN / 'rh-answer-only-v2'
MODEL = 'gpt-6-luna'
BUDGET_USD = 3.0


def make_runners(output=OUTPUT):
    experiment = load_experiment(HERE / 'local.yaml')
    assert experiment.outcome_audit['models'] == [MODEL]
    study = Path(experiment.dag['revise']['output_dir'])
    sources = resolve_study_sources(study, experiment)
    assert len(sources.revisions) == 240
    shared_inputs = {}
    return {
        window.value: prepare_direct_detection(
            DirectDetectionConfig(experiment, study, output / f'direct_{window.value}',
                                  max_concurrency=12, resume=True, window=window),
            sources=sources, shared_inputs=shared_inputs,
        ) for window in RevisionDetectionWindow
    }


def audit():
    """Worker entrypoint with only the loopback relay credential."""
    with audit_owner(OUTPUT), AuditExecutor(12, (MODEL,)) as pool:
        runners = make_runners()
        for runner in runners.values():
            runner.prepare_resume()
        results = {}
        with ThreadPoolExecutor(max_workers=4) as stages:
            futures = {stages.submit(runner.run_prepared, executor=pool): name
                       for name, runner in runners.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = {'exit_code': future.result()}
                except Exception as exc:
                    results[name] = {'exit_code': 1, 'error_type': type(exc).__name__, 'error': str(exc)}
                (OUTPUT / 'stages.json').write_text(json.dumps(results, indent=2) + '\n')
                print(name, results[name], flush=True)
        return int(any(r['exit_code'] for r in results.values()))


def main():
    with (RUN / '.run.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = controlled_process_environment()
        # Real credential remains solely in the parent relay, never in receipts.
        key = dotenv_values(ROOT / '.env.local').get('OPENAI_API_KEY')
        if not key or not key.endswith('IfoA'):
            raise RuntimeError('Confirmed OpenAI credential unavailable')
        ledger = Ledger(OUTPUT / 'budget.json', BUDGET_USD)
        worker_key = 'sk-local-budget-' + secrets.token_hex(24)
        for name in list(env):
            if any(s in name for s in ('API_KEY', 'ACCESS_TOKEN')) or name in (
                'OPENAI_BASE_URL', 'OPENAI_API_BASE', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID',
                'RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY',
            ):
                env.pop(name)
        env.update(OPENAI_API_KEY=worker_key, OPENAI_BASE_URL='http://127.0.0.1:18765/v1',
                   RUBRIC_GEN_OPENAI_BUDGET_URL='http://127.0.0.1:18765/v1',
                   RUBRIC_GEN_OPENAI_REASONING_EFFORT='high',
                   RUBRIC_GEN_RUNTIME_CONFIG=str(HERE / 'runtime.json'),
                   PYTHONPATH=os.pathsep.join((str(ROOT / 'src'), str(HERE))))
        invocation = OUTPUT / 'invocations' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        invocation.mkdir(parents=True)
        command = [sys.executable, '-c', 'from reaudit_rh import audit; raise SystemExit(audit())']
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, env=env, text=True).strip()
        diff = subprocess.check_output(['git', 'diff', '--binary'], cwd=ROOT, env=env)
        (invocation / 'source.diff').write_bytes(diff)
        for relative in (
            'src/rubric_gen/benchmarks/answer_only/detection.py',
            'src/rubric_gen/detection/prompts.py',
            'src/rubric_gen/detection/runner.py',
            'src/rubric_gen/submission_revision/evaluation/evidence.py',
            'experiments/healthbench-hard-result20/reaudit_rh.py',
            'experiments/healthbench-hard-result20/budget_proxy.py',
            'experiments/healthbench-hard-result20/local.yaml',
            'experiments/healthbench-hard-result20/runtime.json',
        ):
            dest = invocation / 'source' / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, dest)
        receipt = dict(status='running', pid=os.getpid(), command=command,
                       started_utc=datetime.now(timezone.utc).isoformat(), git_head=head,
                       host='local Mac', model=MODEL, reasoning_effort='high',
                       assignments=240, windows=4, budget_usd=BUDGET_USD,
                       assignment_workers=0, shared_audit_queue=1, window_coordinators=4,
                       provider_concurrency=12, audit_concurrency=12, fanout=1,
                       cpu=os.cpu_count(), memory_gib=24, resource_reservation='none; local process',
                       expected_wall_minutes=[10, 20], scope='RH only; saved solver evidence')
        receipt_path = invocation / 'receipt.json'
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        server = None
        try:
            server = start_proxy(key, ledger, worker_key)
            with (invocation / 'audit.log').open('w') as log:
                result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            receipt.update(exit_code=result.returncode, status='completed' if result.returncode == 0 else 'failed')
        except BaseException:
            receipt['status'] = 'failed'
            raise
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            receipt.update(ended_utc=datetime.now(timezone.utc).isoformat(),
                           budget=json.loads((OUTPUT / 'budget.json').read_text()))
            receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
        if receipt['exit_code']:
            raise SystemExit(receipt['exit_code'])


if __name__ == '__main__':
    main()
