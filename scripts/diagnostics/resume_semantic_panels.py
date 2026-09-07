"""Private recovery through existing rubric/quality stage APIs.

Operator prerequisite: the prior semantic-stage writer has terminated. Never
run against directories still owned by a live detect invocation. Independent
direct-stage recovery may continue in its disjoint directories.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import (
    RubricFreeScoreRunner,
    RubricScoreRunner,
)
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import load_experiment


CONCURRENCY = 1


def snapshot(roots):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest()
            for root in roots for p in root.glob('records/*.json')}


def main(experiment_path):
    experiment = load_experiment(Path(experiment_path).resolve())
    study = Path(str(experiment.dag['revise']['output_dir']))
    paraphrases = Path(str(experiment.dag['paraphrase']['output_dir']))
    audit = Path(str(experiment.dag['detect']['output_dir']))
    roots = {name: audit / name for name in (
        'rubric_score', 'absolute_score', 'pairwise_preference',
    )}
    for name, root in roots.items():
        if not (root / 'manifest.json').is_file():
            raise ValueError(f'{name}: require an existing stage manifest')
    rubric_config = EvaluationConfig(
        experiment=experiment, study_dir=study, paraphrase_dir=paraphrases,
        output_dir=roots['rubric_score'], max_concurrency=CONCURRENCY, resume=True,
    )
    quality_config = EvaluationConfig(
        experiment=experiment, study_dir=study, paraphrase_dir=paraphrases,
        output_dir=audit, max_concurrency=CONCURRENCY, resume=True,
    )
    targets = load_evaluation_targets(rubric_config)
    rubric = RubricScoreRunner(rubric_config, targets)
    quality = RubricFreeScoreRunner(quality_config, targets)
    rubric.preflight()
    quality.preflight()
    statuses = {}
    errors = []
    for name, runner, stage_roots in (
        ('rubric_score', rubric, [roots['rubric_score']]),
        ('rubric_free_score', quality,
         [roots['absolute_score'], roots['pairwise_preference']]),
    ):
        before = snapshot(stage_roots)
        print(json.dumps({'time': datetime.now().astimezone().isoformat(),
                          'stage': name, 'event': 'resume',
                          'concurrency': CONCURRENCY,
                          'preserved_records': len(before)}), flush=True)
        try:
            statuses[name] = int(runner.run())
        except Exception as exc:
            errors.append((name, exc))
        finally:
            after = snapshot(stage_roots)
            changed = [str(p) for p, digest in before.items()
                       if after.get(p) != digest]
            if changed:
                raise RuntimeError(f'Existing successful records changed: {changed}')
            print(json.dumps({'time': datetime.now().astimezone().isoformat(),
                              'stage': name, 'event': 'preservation_checked',
                              'unchanged_records': len(before),
                              'new_records': len(after) - len(before)}), flush=True)
    print(json.dumps({'semantic_stage_exit_statuses': statuses,
                      'exception_stages': [name for name, _ in errors]}), flush=True)
    if errors:
        raise RuntimeError('Semantic recovery finished with stage exceptions') from errors[0][1]
    return int(any(statuses.values()))


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Supply the existing experiment YAML path')
    raise SystemExit(main(sys.argv[1]))
