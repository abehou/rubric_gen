"""Reuse selected/development variants; generate only missing new-task heldouts."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrases import ParaphraseRunConfig, ParaphraseRunner
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run, validate_request_policy

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path('/data/user_data/aydanh/rubric_gen/pools/paraphrases/biomnibench/confirmation-20260909/additional25')
ORIGINAL = {
    'queue6': Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-results30-20260912'),
    'queue7': Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-results45-inputs-20260912'),
}


def prepare_selected(experiment):
    """Copy native producer bytes into a new consumer pool; never edit metadata."""
    validate_paraphrase_run(SOURCE, experiment)
    output = Path(experiment.dag['paraphrase']['output_dir'])
    runner = ParaphraseRunner(ParaphraseRunConfig(experiment, output, 4))
    if output.is_symlink():
        raise ValueError('consumer output must be a regular directory')
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / 'manifest.json'
    if not manifest.exists():
        if any(output.iterdir()):
            raise ValueError('unowned files in new consumer pool')
        write_json_atomic(manifest, runner._new_manifest())
    records = []
    for task in experiment.task_ids:
        dst = output / 'tasks' / task
        dst.mkdir(parents=True, exist_ok=True)
        for index in (0, 1):
            src = SOURCE / 'tasks' / task
            names = [f'variant-{index:03d}.txt', f'variant-{index:03d}.json']
            failures = src / f'variant-{index:03d}.failures'
            if failures.exists():
                names.extend(str(p.relative_to(src)) for p in failures.rglob('*') if p.is_file())
            for name in names:
                target = dst / name
                data = (src / name).read_bytes()
                if target.exists():
                    if target.read_bytes() != data:
                        raise ValueError(f'consumer differs from selected/development producer: {target}')
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open('xb') as handle:
                        handle.write(data)
            records.append({'task': task, 'variant': index, 'source': str(src / names[0]),
                            'consumer': str(dst / names[0]), 'metadata_unchanged': True})
    return runner, records


def main():
    scope = sys.argv[1]
    if scope not in ORIGINAL:
        raise ValueError('queue6 or queue7 scope required')
    membership = json.loads((ROOT / 'experiments/biomnibench-v21-to45/queue6/membership.json').read_text())
    tasks = membership['additional10'] if scope == 'queue6' else membership['results45'][30:]
    for key in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        value = os.environ.get(key) or dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(key)
        if value:
            os.environ[key] = value
    rows = []
    for task in tasks:
        config = ORIGINAL[scope] / f'experiments/biomnibench-v21-to45/{scope}/configs/{task}.yaml'
        experiment = load_experiment(config)
        try:
            runner, copied = prepare_selected(experiment)
            code = runner.run()
            if code:
                raise RuntimeError(f'native paraphrase returned {code}')
            master = (experiment.task_dir(task) / 'tests' / 'rubric.txt').read_text()
            for i in (2, 3, 4):
                validate_request_policy(runner.root / 'tasks' / task / f'variant-{i:03d}.json',
                                        master, experiment.rubric_paraphrases)
            for row in copied:
                if Path(row['source']).read_bytes() != Path(row['consumer']).read_bytes():
                    raise RuntimeError('selected/development changed during generation')
            result = {'task': task, 'status': 'completed', 'copied_selected_development': copied,
                      'heldout_variants': [2, 3, 4], 'prompt_source_commit': '47463ca',
                      'old_twenty_heldouts_changed': False, 'output': str(runner.root)}
        except Exception as exc:
            result = {'task': task, 'status': 'failed', 'error_type': type(exc).__name__, 'error': str(exc)}
        rows.append(result)
        receipt = ROOT / f'experiments/biomnibench-v21-to45/queue8/heldouts-{scope}-{os.environ["SLURM_JOB_ID"]}.json'
        write_json_atomic(receipt, {'job': os.environ['SLURM_JOB_ID'], 'scope': scope, 'tasks': rows})
        print(json.dumps(result), flush=True)
    return int(any(r['status'] != 'completed' for r in rows))


if __name__ == '__main__':
    raise SystemExit(main())
