"""Run the approved local four-condition HealthBench Dev3 with one OpenAI key."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('/private/tmp/rubric-gen-healthbench-live-20260925')
CONFIG = Path(__file__).with_name('dev3.yaml')
RUNTIME = Path(__file__).with_name('runtime.json')
OUTPUT = ROOT / 'runs/healthbench-hard-local-mac-20260925-v2'
SOURCE_COMMIT = 'b89b638ba80338104d618ce90f472f4315a6aefe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-key-suffix', required=True)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    key = dotenv_values(ROOT / '.env.local').get('OPENAI_API_KEY')
    if not key or key.startswith('sk-ant-') or not key.endswith(args.expected_key_suffix):
        raise SystemExit('OPENAI_API_KEY is missing, belongs to Anthropic, or does not match the confirmed suffix.')
    sys.path.insert(0, str(SOURCE / 'src'))
    from rubric_gen.runtime.process_environment import controlled_process_environment
    from rubric_gen.submission_revision.experiment import load_experiment
    env = controlled_process_environment()
    for name in list(env):
        if ('API_KEY' in name or name in {'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL',
                                        'OPENAI_API_BASE', 'OPENAI_ORG_ID', 'OPENAI_PROJECT_ID'}):
            env.pop(name)
    env.update(OPENAI_API_KEY=key, CODEX_API_KEY=key,
               OPENAI_BASE_URL='https://api.openai.com/v1',
               PYTHONPATH=str(SOURCE / 'src'), RUBRIC_GEN_RUNTIME_CONFIG=str(RUNTIME))
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, env=env, text=True).strip()
    if commit != SOURCE_COMMIT or subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, env=env):
        raise SystemExit('Runtime checkout differs from the reviewed source; inspect before launching.')
    config = CONFIG.with_name('smoke.yaml') if args.smoke else CONFIG
    output = OUTPUT / 'smoke' if args.smoke else OUTPUT
    assignment_workers = 1 if args.smoke else 6
    experiment = load_experiment(config)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    invocation = output / 'invocations' / stamp
    invocation.mkdir(parents=True, exist_ok=False)
    receipt = dict(source=commit, experiment_id=experiment.experiment_id, config=str(config),
                   pid=os.getpid(), started_utc=stamp, key_suffix=args.expected_key_suffix,
                   assignment_count=len(experiment.assignments), assignment_workers=assignment_workers,
                   outer_queues=1, aggregate_concurrency=12, internal_fanout=4,
                   audit_concurrency=12, stages=[])
    for stage, extra, workers in [
        ('seed', [], 6), ('paraphrase', [], 6),
        ('revise', ['--assignment-workers', str(assignment_workers)], 12),
        ('detect', ['--study-dir', str(output / 'studies' / experiment.experiment_id)], 12),
    ]:
        command = [sys.executable, '-m', 'rubric_gen.cli', stage, '--experiment', str(config),
                   '--max-concurrency', str(workers), *extra]
        if stage in {'revise', 'detect'}:
            command.append('--resume')
        record = dict(stage=stage, command=command, status='running')
        receipt['stages'].append(record)
        (invocation / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(f'{stage}: {invocation / (stage + ".log")}', flush=True)
        with (invocation / f'{stage}.log').open('w') as log:
            result = subprocess.run(command, cwd=SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT)
        record.update(status='completed' if result.returncode == 0 else 'failed', exit_code=result.returncode)
        (invocation / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
