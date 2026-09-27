"""Offline evidence-parity check and RH-only cost estimate; never calls a provider."""
import json
import math
from pathlib import Path
from unittest.mock import patch

from rubric_gen.runtime.process_environment import install_controlled_process_environment
from rubric_gen.detection.prompts import _reward_hacking_requests
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUN = ROOT / 'runs/healthbench-hard-challenge20-local-20260926'


@patch('rubric_gen.runtime.capacity.emit', lambda *args, **kwargs: None)
def inspect():
    experiment = load_experiment(HERE / 'local.yaml')
    study = Path(experiment.dag['revise']['output_dir'])
    sources = resolve_study_sources(study, experiment)
    assert len(sources.revisions) == 240
    previous = RUN / 'audits' / experiment.experiment_id
    cache = {}
    result = {
        'model': 'gpt-6-luna', 'reasoning_effort': 'high',
        'pricing_source': 'https://developers.openai.com/api/docs/pricing',
        'pricing_checked': '2026-09-26',
        'input_usd_per_million': .125, 'output_usd_per_million': .5,
        'assumptions': 'All input charged at cache-write rate, no cache savings; '
                       'new output allowance forecast is max(512, 3x observed tokens) '
                       'per request, including reasoning. Not a hard cost bound.',
        'windows': {},
    }
    for window in RevisionDetectionWindow:
        paths = list((previous / f'direct_{window.value}').rglob('summary.json'))
        assert len(paths) == 1
        summary_path = paths[0]
        old = json.loads(summary_path.read_text())
        records = {r['source_path']: r for r in old['records']}
        source = revision_detection_source(
            tuple(r.directory for r in sources.revisions),
            tasks_dir=experiment.tasks_dir,
            experiment_ids=(experiment.experiment_id,), window=window,
            resolved_sources=sources.revisions, shared_inputs=cache,
        )
        counts = dict(assignments=0, requests=0, unchanged_evidence_requests=0,
                      old_input_tokens=0, estimated_input_tokens=0,
                      old_output_tokens=0, estimated_output_tokens=0,
                      max_estimated_request_input_tokens=0)
        for case in source.cases:
            record = records[str(case.path)]
            assert record['status'] == 'completed'
            payload = source.prompt(case, 'rh')
            requests = _reward_hacking_requests(
                payload, evidence_chars=record['compact_evidence']['chunk_character_limit'],
                max_output_tokens=4096,
            )
            assert len(requests) == record['verdict']['chunk_count']
            counts['assignments'] += 1
            for i, request in enumerate(requests, start=1):
                chunk = summary_path.parent / 'cases' / record['case_id'] / 'gpt-6-luna' / f'chunk-{i:03d}'
                attempts = [json.loads(p.read_text()) for p in sorted(chunk.glob('attempt-*.json'))]
                completed = [a for a in attempts if 'generation' in a]
                prior = completed[-1]
                previous_request = prior['identity']['request']
                assert request.evidence == previous_request['evidence'], (window, case.path, i)
                assert request.schema == previous_request['schema']
                assert f'Detection window: {window.value}' in request.instructions
                assert 'Answer-only task guidance:' in request.instructions
                usage = prior['generation']['provider_metadata']['usage']
                added_bytes = len(request.instructions.encode()) - len(previous_request['instructions'].encode())
                assert added_bytes > 0
                inp = usage['input_tokens'] + math.ceil(added_bytes / 2)
                # Same two-characters/token allowance as the native monitor planner.
                assert inp < 150_000, 'New context may require native rechunking'
                counts['requests'] += 1
                counts['unchanged_evidence_requests'] += 1
                counts['old_input_tokens'] += usage['input_tokens']
                counts['estimated_input_tokens'] += inp
                counts['old_output_tokens'] += usage['output_tokens']
                counts['estimated_output_tokens'] += max(512, 3 * usage['output_tokens'])
                counts['max_estimated_request_input_tokens'] = max(counts['max_estimated_request_input_tokens'], inp)
        assert counts['assignments'] == 240
        counts['old_observed_usd'] = old['cost']['observed_api_usd']
        counts['estimated_usd'] = (counts['estimated_input_tokens'] * .125
                                   + counts['estimated_output_tokens'] * .5) / 1e6
        result['windows'][window.value] = counts
    result['total_estimated_usd'] = sum(w['estimated_usd'] for w in result['windows'].values())
    result['old_total_observed_usd'] = sum(w['old_observed_usd'] for w in result['windows'].values())
    return result


if __name__ == '__main__':
    install_controlled_process_environment()
    result = inspect()
    (HERE / 'rh-reaudit-estimate.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
