"""Resource profiles and compact reporting around the ordinary experiment CLI."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tempfile

from dotenv import dotenv_values
from monitor import Monitor
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment

PROFILES = {'dev3-4': (4, 4), 'dev3-8': (8, 8), 'results20': (32, 32), 'inspection': (1, 4)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    parser.add_argument('command', choices=['run', 'revise', 'detect'])
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    cpus, workers = PROFILES[args.profile]
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ['SLURM_CPUS_PER_TASK']) < cpus:
        raise RuntimeError(f'{args.profile} requires {cpus} allocated CPUs')
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('use the locked Python 3.12 environment')
    exp = load_experiment(args.experiment.resolve())
    root = Path('/data/user_data/aydanh/rubric_gen')
    if not root.is_dir():
        raise RuntimeError('persistent compute storage is unavailable')
    # Existing historical inputs may remain in home; new output/cache paths may not.
    for stage in ('revise', 'detect'):
        Path(exp.dag[stage]['output_dir']).resolve().relative_to(root)
    if args.profile == 'inspection' and args.command != 'detect':
        raise ValueError('inspection profile does not run solver assignments')
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        value = os.environ.get(key) or dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(key)
        if value:
            os.environ[key] = value
    command = [sys.executable, '-m', 'rubric_gen.cli', args.command,
               '--experiment', str(exp.path), '--max-concurrency', str(workers)]
    if args.command in {'run', 'revise'}:
        command += ['--assignment-workers', str(workers)]
    if args.resume:
        command += ['--resume']
    reports = Path.cwd() / 'runs'
    reports.mkdir(exist_ok=True)
    report = Path(tempfile.mkdtemp(prefix=f'runtime-{os.environ["SLURM_JOB_ID"]}-', dir=reports))
    receipt = {'command': command, 'profile': args.profile, 'assignment_workers': workers,
               'request_workers': workers, 'shared_capacity': policy(),
               'experiment_id': exp.experiment_id, 'source': str(Path.cwd()),
               'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
               'source_status': subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], text=True)}
    write_json_atomic(report / 'launch.json', receipt)
    print(json.dumps(receipt), flush=True)
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = f"{os.environ['SLURM_JOB_ID']}-{os.getpid()}"
    monitor = Monitor(policy()['coordination_dir'], report / 'metrics.jsonl', [exp.dag['revise']['output_dir']])
    with (report / 'execution.log').open('x') as output:
        child = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        def stop(_signal, _frame):
            # The native controller owns solver checkpoints and terminal cleanup.
            child.send_signal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        with ThreadPoolExecutor(max_workers=1) as observer:
            finished = observer.submit(child.wait)
            while True:
                sample = monitor.sample()
                sample.update(configured_assignment_workers=workers, configured_request_workers=workers,
                              profile=args.profile, source=str(Path.cwd()))
                write_json_atomic(report / 'status.json', sample)
                print(json.dumps({k: sample[k] for k in (
                    'assignments','completed_assignments_per_hour','sampled_cpu_cores','rss_kib',
                    'active_provider_slots','active_audit_studies','elapsed_seconds')}), flush=True)
                try:
                    code = finished.result(timeout=30)
                    break
                except TimeoutError:
                    continue
    write_json_atomic(report / 'result.json', {'exit_code': code, 'completed_at': time.time(), **receipt})
    return code


if __name__ == '__main__':
    raise SystemExit(main())
