"""Check saved BioMNIBench audit reuse with the existing reviewed runtime patch."""
import json
import sys
import time
from pathlib import Path

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner

ROOT = Path(__file__).resolve().parents[3]
kind = sys.argv[1]
if kind == 'queue2':
    original = Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-appendix-queue2-20260912')
    cells = ('R1', 'R2')
elif kind == 'queue3':
    original = Path('/home/aydanh/repos/rubric_gen/runs/babel-code/trace-feedback-matrix-queue3-20260912')
    cells = ('semi-fixed', 'score_only-fixed')
else:
    raise ValueError('Expected queue2 or queue3')

records = []
started = time.monotonic()
for cell in cells:
    for task in ('da-3-4', 'da-11-1', 'da-18-1'):
        experiment = load_experiment(original / f'experiments/biomnibench-v21-to45/{kind}/configs/{cell}/{task}.yaml')
        study = Path(experiment.dag['revise']['output_dir'])
        output = Path(experiment.dag['detect']['output_dir']) / 'rubric_score'
        if not (output / 'manifest.json').exists():
            records.append(dict(cell=cell, task=task, status='not_started', provider_calls=0))
            continue
        before = {p: p.read_bytes() for p in (output / 'records').glob('*.json')}
        config = EvaluationConfig(experiment=experiment, study_dir=study,
            paraphrase_dir=Path(experiment.dag['paraphrase']['output_dir']), output_dir=output,
            max_concurrency=32, resume=True)
        sources = resolve_study_sources(study, experiment)
        targets = load_evaluation_targets(config, sources)
        runner = RubricScoreRunner(config, targets)
        runner.preflight()
        complete = runner.prepare_resume()
        planned = runner._prepared.jobs
        # Use native adoption/validation; do not reinterpret or rewrite old metadata.
        for path, content in before.items():
            if path.read_bytes() != content:
                raise RuntimeError(f'Completed record changed during preparation: {path}')
        missing = [] if complete else [j for j in planned if not (output / 'records' / (j.key + '.json')).exists()]
        row = dict(cell=cell, task=task, status='native_replay_valid',
            preserved_record_count=len(before), planned_count=len(planned), complete_stage_reused=complete,
            missing_count=len(missing), missing_jobs=[dict(key=j.key, model=j.model) for j in missing],
            provider_calls=0, source_config=str(experiment.path), output=str(output))
        records.append(row)
        print(json.dumps({k: v for k, v in row.items() if k not in ('missing_jobs', 'source_config', 'output')}), flush=True)
out = ROOT / f'docs/reports/2026-09-12/biomnibench-v21-to45/queue8/runtime-replay-{kind}.json'
out.write_text(json.dumps(dict(reviewed_patch='c451942', records=records,
    elapsed_seconds=time.monotonic() - started, provider_calls=0), indent=2) + '\n')
