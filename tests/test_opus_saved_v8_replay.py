"""Lossless saved-response replay for the three 120-criterion v8 tail failures."""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from rubric_gen.submission_revision.evaluation import indexed_rubric as wire
from rubric_gen.submission_revision.evaluation import jobs, resume, rubric_judge as judge_module
from rubric_gen.submission_revision.evaluation.rubric_score import (
    _rubric_score_assignment_reference_sha256, _rubric_score_attempt_id,
)
from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricGeneration, FullRubricJudgeError
from test_evaluation_rubric_judge import _many_criterion_rubric
from test_opus_cardinality import _fixture_panel
from test_runtime_reliability import _text, _wire


def _pipe_value(items):
    value = _text(items)
    value['criteria_text'] = value['criteria_text'].replace('\n', '|')
    return value


def _records(value, count, *, contract=wire.STRUCTURED_OUTPUT, replay=True):
    rubric = _many_criterion_rubric(count)
    spec = judge_module.build_rubric_score_run_spec(
        rubric_text=rubric, review_text='evidence', answer_text='answer',
        requested_model='claude-opus-5', seed=7, indexed_contract=contract)
    generation = FullRubricGeneration(text=json.dumps(value), provider=spec.provider,
        requested_model=spec.requested_model, effective_model=spec.requested_model,
        response_id='saved-response', request_parameters=judge_module._request_parameters(spec),
        usage={'output_tokens': 300})
    return judge_module._records_from_generation(spec, generation, rubric_text=rubric,
                                                 replay_saved_response=replay)


@pytest.mark.parametrize('count', [1, 2, 67, 120, 145, 306, 872])
def test_saved_v8_pipe_rows_preserve_exact_canonical_records_and_scores(count):
    items = [f'{i % 2}| evidence {i} | retain | pipes; 4|label ' for i in range(count)]
    value = _pipe_value(items)
    decoded = wire.replay_saved_v8_output(json.dumps(value), count)
    assert decoded == wire.decode_output(json.dumps(_text(items)), count)
    assert decoded == wire.decode_output(json.dumps(_wire(items)), count, contract=wire.V5_STRUCTURED_OUTPUT)
    assert [item['reason'] for item in json.loads(decoded)['criteria']] == [s.split('|', 1)[1] for s in items]
    records = [_records(value, count), _records(_text(items), count, replay=False),
               _records(_wire(items), count, contract=wire.V5_STRUCTURED_OUTPUT, replay=False)]
    assert records[0].score == records[1].score == records[2].score
    assert records[0].evaluation['criteria'] == records[1].evaluation['criteria'] == records[2].evaluation['criteria']
    # The normal production decoder still rejects one-line multi-criterion output.
    if count > 1:
        with pytest.raises(FullRubricJudgeError, match='criterion lines'):
            wire.decode_output(json.dumps(value), count)


@pytest.mark.parametrize('damage', [
    'missing-first', 'missing-middle', 'missing-last', 'reordered', 'duplicate', 'extra',
    'wrong-index', 'leading-zero-index', 'negative-index', 'nondecimal-index',
    'negative-level', 'leading-zero-level', 'nondecimal-level', 'level-out-of-bounds',
    'empty-reason', 'empty-overall', 'extra-marker-in-reason', 'overlapping-markers',
    'leading-blank', 'interior-newline', 'double-terminal-newline',
    'missing-reason-field', 'missing-overall', 'extra-key', 'nonstring-text',
])
def test_saved_v8_never_infers_fields_or_selects_a_subset_of_markers(damage):
    rows = [f'{i}|0|evidence' for i in range(120)]
    if damage == 'missing-first': rows.pop(0)
    elif damage == 'missing-middle': rows.pop(60)
    elif damage == 'missing-last': rows.pop()
    elif damage == 'reordered': rows[60], rows[61] = rows[61], rows[60]
    elif damage == 'duplicate': rows.insert(60, rows[60])
    elif damage == 'extra': rows.append('120|0|extra')
    elif damage == 'wrong-index': rows[60] = '999|0|evidence'
    elif damage == 'leading-zero-index': rows[60] = '060|0|evidence'
    elif damage == 'negative-index': rows[60] = '-60|0|evidence'
    elif damage == 'nondecimal-index': rows[60] = 'sixty|0|evidence'
    elif damage == 'negative-level': rows[60] = '60|-1|evidence'
    elif damage == 'leading-zero-level': rows[60] = '60|00|evidence'
    elif damage == 'nondecimal-level': rows[60] = '60|false|evidence'
    elif damage == 'level-out-of-bounds': rows[60] = '60|2|evidence'
    elif damage == 'empty-reason': rows[60] = '60|0| \t'
    elif damage == 'extra-marker-in-reason': rows[60] += '|999|0|ambiguous prose'
    elif damage == 'overlapping-markers': rows[60] = '60|0|7|numeric reason'
    elif damage == 'missing-reason-field': rows[-1] = '119|0'
    value = {'criteria_text': '|'.join(rows), 'overall_reasoning': 'overall'}
    if damage == 'empty-overall': value['overall_reasoning'] = ' \t'
    elif damage == 'leading-blank': value['criteria_text'] = '\n' + value['criteria_text']
    elif damage == 'interior-newline': value['criteria_text'] = value['criteria_text'].replace('|60|', '\n60|')
    elif damage == 'double-terminal-newline': value['criteria_text'] += '\n\n'
    elif damage == 'missing-overall': del value['overall_reasoning']
    elif damage == 'extra-key': value['extra'] = 'not allowed'
    elif damage == 'nonstring-text': value['criteria_text'] = rows
    with pytest.raises(FullRubricJudgeError):
        _records(value, 120)


@pytest.mark.parametrize('key', ['criteria_text', 'overall_reasoning'])
def test_saved_v8_duplicate_json_keys_are_not_collapsed(key):
    value = _pipe_value(['0|evidence'] * 120)
    text = json.dumps(value)[:-1] + ', ' + json.dumps(key) + ': ' + json.dumps(value[key]) + '}'
    with pytest.raises(FullRubricJudgeError, match='duplicate JSON key'):
        wire.replay_saved_v8_output(text, 120)


@pytest.mark.parametrize('ending', ['\n', '\r\n'])
def test_saved_v8_accepts_one_terminal_line_ending_without_trimming_reasons(ending):
    value = _pipe_value(['0| reason | retained '] * 120)
    original = wire.replay_saved_v8_output(json.dumps(value), 120)
    value['criteria_text'] += ending
    assert wire.replay_saved_v8_output(json.dumps(value), 120) == original


def test_real_saved_v8_tail_candidates_read_only():
    """Opt-in compute replay of all nine recorded attempts, without publication."""
    receipt = os.environ.get('PAPERBENCH_V8_TAIL_RECEIPT')
    if receipt is None:
        pytest.skip('real saved responses require the compute-only tail receipt')
    evidence = json.loads(Path(receipt).read_text())
    accepted = rejected = 0
    earliest = {}
    for judgment in evidence['attempts']:
        key = judgment['judgment_key']
        for attempt in judgment['attempts']:
            path = Path(attempt['saved_response'])
            before = path.read_bytes()
            raw = json.loads(before)
            assert raw['request']['execution']['structured_output_contract'] == wire.STRUCTURED_OUTPUT
            levels = judge_module.parse_rubric_levels_strict(json.loads(raw['request']['payload'])['rubric_text'])
            assert len(levels) == 120
            try:
                canonical = wire.replay_saved_v8_output(raw['generation']['text'], len(levels))
                judge_module.parse_rubric_score_output(canonical, levels)
            except FullRubricJudgeError:
                assert not attempt['native_canonical_decode_after_delimiter_conversion']
                rejected += 1
            else:
                assert attempt['native_canonical_decode_after_delimiter_conversion']
                accepted += 1
                earliest[key] = min(earliest.get(key, attempt['attempt']), attempt['attempt'])
            assert path.read_bytes() == before
    assert (accepted, rejected) == (5, 4)
    assert earliest == {'0164cfe5c2eb1d5ff576b6b14fda387d': 2,
                        '5123ea33722de6bd82e6535b02c7117a': 2,
                        'af2320beaa217729634458ea4a3d90d4': 1}


def _prepare_output(runner):
    prepared = runner._prepared
    prior = json.loads((runner.root / 'manifest.json').read_text())
    current = {**prior, 'predispatch_plan': prepared.predispatch_plan,
        'implementation_identity': jobs._rubric_score_implementation_identity(prepared.unique_jobs),
        'assignment_reference_identity_sha256': _rubric_score_assignment_reference_sha256(prepared.jobs)}
    resume.prepare_stage_output(runner.output, current, True, prepared.jobs)


def _add_historical_v5_manifest(runner, latest, missing):
    """Keep latest v8 attempts in summary.json and an earlier v5 plan/attempts.

    All three implementation identities differ: historical v5, saved v8, and
    the running decoder repair. Both historical and latest raw files survive.
    """
    prior = json.loads((runner.root / 'manifest.json').read_text())
    runner.output.write_json(('summary.json',), {**prior, 'status': 'incomplete'})
    historical = [replace(job, grading_identity={**job.grading_identity,
        'scoring_implementation_sha256': 'c' * 64}, evaluation_implementation_sha256='d' * 64)
        for job in latest]
    entries = [{**entry, 'semantic_key': job.key, 'grading_identity': job.grading_identity}
               for entry, job in zip(prior['predispatch_plan']['jobs'], historical, strict=True)]
    runner.output.write_json(('manifest.json',), {**prior,
        'implementation_identity': {'evaluation_sha256': 'd' * 64},
        'predispatch_plan': {'jobs': entries},
        'assignment_reference_identity_sha256': _rubric_score_assignment_reference_sha256(tuple(historical))})
    for latest_job, old in zip(latest, historical, strict=True):
        if latest_job not in missing:
            continue
        judge = runner._judge_for_job(old)
        review, answer = judge.review_inputs(old.submission)
        spec = judge_module.build_rubric_score_run_spec(rubric_text=judge.rubric.text,
            review_text=review, answer_text=answer, requested_model=old.model,
            seed=judge._grading_seed(review, answer), indexed_contract=wire.V5_STRUCTURED_OUTPUT)
        value = _wire(['0|historical evidence'] * spec.criterion_count)
        value['criteria']['full_blocks'].append(value['criteria']['full_blocks'][0])
        generation = FullRubricGeneration(text=json.dumps(value), provider=spec.provider,
            requested_model=old.model, effective_model=old.model, response_id='historical-v5',
            request_parameters=judge_module._request_parameters(spec), usage={'output_tokens': 300})
        attempt_id = _rubric_score_attempt_id(old)
        root = judge._evaluation_root(old.submission, attempt_id)
        attempts = root.parent / f'{attempt_id}.attempts'
        attempts.mkdir(parents=True)
        raw = {'request': {'execution': spec.as_json(),
            'payload': judge_module.rubric_score_payload(judge.rubric.text, review, answer),
            'schema': wire.output_schema(spec.criterion_count, contract=wire.V5_STRUCTURED_OUTPUT)},
            'generation': generation.__dict__}
        (attempts / 'attempt-001.response.json').write_text(json.dumps(raw))
        state = {'identity': {'scoring_identity': old.grading_identity,
            'review_input_sha256': old.review_input_sha256, 'answer_input_sha256': old.answer_input_sha256},
            'attempt': 1, 'failure_category': 'invalid_response'}
        (attempts / 'attempt-001.json').write_text(json.dumps(state))


def test_native_897_opus_900_sol_only_three_local_replays_no_provider_calls(tmp_path, monkeypatch):
    runner, planned, old = _fixture_panel(tmp_path, monkeypatch, valid=897, missing=3,
        salvage=3, sol=900, old_contract=wire.STRUCTURED_OUTPUT, missing_criterion_count=120,
        saved_v8_attempts=[(2, 3), (2,), (1, 2)])
    _add_historical_v5_manifest(runner, old, old[897:900])
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in runner.root.rglob('*') if p.is_file()}
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError('saved replay and valid records must not call providers')
    monkeypatch.setattr(judge_module, '_generate_response', forbidden)
    accepted = rejected = 0
    for original in old[897:900]:
        for path in (runner.root / 'artifacts' / original.key).rglob('attempt-*.response.json'):
            value = json.loads(json.loads(path.read_text())['generation']['text'])
            try:
                _records(value, 120)
            except FullRubricJudgeError:
                rejected += 1
            else:
                accepted += 1
    assert (accepted, rejected) == (5, 4)
    runner.preflight()
    assert len(runner._reused_records) == 1797
    assert len(runner._saved_response_replays) == 3
    pending = [j for j in runner._prepared.unique_jobs if j.key not in runner._reused_records]
    assert len(pending) == 3 and all(j.model == 'claude-opus-5' for j in pending)
    assert {j.key for j in pending} == set(runner._saved_response_replays)
    for i, number in enumerate((2, 2, 1)):
        candidate = runner._saved_response_replays[planned[897 + i].key]
        assert candidate.attempt_path.name == f'attempt-{number:03d}.json'
        assert old[897 + i].key in candidate.attempt_path.parts
        assert candidate.identity['scoring_identity']['scoring_implementation_sha256'] == 'a' * 64
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in before.items())
    _prepare_output(runner)
    results = [runner._run_job(job) for job in runner._prepared.unique_jobs]
    assert len(results) == 1800 and calls == []
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in before.items())
    for job in pending:
        candidate = runner._saved_response_replays[job.key]
        saved = json.loads(candidate.response_path.read_text())
        record = json.loads((runner.root / 'records' / f'{job.key}.json').read_text())
        usage = json.loads((Path(record['evaluation_path']).parent / 'usage.json').read_text())
        assert record['engine_execution'] == saved['request']['execution']
        assert usage['call']['response_id'] == saved['generation']['response_id']
        assert usage['call']['request_parameters'] == saved['generation']['request_parameters']
        assert usage['call']['raw_usage'] == saved['generation']['usage']
        assert usage['local_response_replay'] == {
            'response_path': str(candidate.response_path), 'attempt_path': str(candidate.attempt_path),
            'producer_identity': candidate.identity}
        assert record['grading_identity'] == job.grading_identity
    # Publication is native-valid on the next resume, with all old provenance intact.
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in runner.root.rglob('*') if p.is_file()}
    runner._prepared = None
    runner.preflight()
    assert len(runner._reused_records) == 1800 and not runner._saved_response_replays
    for job in runner._prepared.unique_jobs:
        runner._run_job(job)
    assert calls == []
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in after.items())


def test_native_v8_replay_does_not_combine_incomplete_attempts(tmp_path, monkeypatch):
    runner, _, old = _fixture_panel(tmp_path, monkeypatch, valid=0, missing=1, salvage=0,
        old_contract=wire.STRUCTURED_OUTPUT, missing_criterion_count=120)
    rows = [f'{i}|0|evidence' for i in range(120)]
    for path in (runner.root / 'artifacts' / old[0].key).rglob('attempt-*.response.json'):
        raw = json.loads(path.read_text())
        missing = int(path.name.split('-')[1].split('.')[0]) - 1
        raw['generation']['text'] = json.dumps({'criteria_text': '|'.join(rows[:missing] + rows[missing + 1:]),
                                              'overall_reasoning': 'overall'})
        path.write_text(json.dumps(raw))
    monkeypatch.setattr(judge_module, '_generate_response', lambda *a, **k: pytest.fail('provider call'))
    runner.preflight()
    assert not runner._saved_response_replays and not runner._reused_records


@pytest.mark.parametrize('damage', ['scope', 'key', 'grading-semantics', 'evaluation-identity', 'duplicate-binding'])
def test_latest_summary_discovery_requires_exact_producer_scientific_binding(tmp_path, monkeypatch, damage):
    runner, _, old = _fixture_panel(tmp_path, monkeypatch, valid=0, missing=1, salvage=1,
        old_contract=wire.STRUCTURED_OUTPUT, missing_criterion_count=120)
    _add_historical_v5_manifest(runner, old, old)
    path = runner.root / 'summary.json'
    summary = json.loads(path.read_text())
    entry = summary['predispatch_plan']['jobs'][0]
    if damage == 'scope': summary['kind'] = 'another-study'
    elif damage == 'key': entry['semantic_key'] = 'wrong-key'
    elif damage == 'grading-semantics': entry['grading_identity']['review_mode'] = 'answer'
    elif damage == 'evaluation-identity': summary['implementation_identity']['evaluation_sha256'] = 'e' * 64
    else: summary['predispatch_plan']['jobs'].append(entry)
    path.write_text(json.dumps(summary))
    monkeypatch.setattr(judge_module, '_generate_response', lambda *a, **k: pytest.fail('provider call'))
    with pytest.raises(RuntimeError, match='saved rubric response (summary|plan)'):
        runner.preflight()


@pytest.mark.parametrize('damage', ['level-out-of-bounds', 'empty-overall', 'wrong-provider', 'wrong-model', 'wrong-contract'])
def test_native_v8_replay_checks_canonical_bounds_and_recorded_provenance(tmp_path, monkeypatch, damage):
    runner, _, old = _fixture_panel(tmp_path, monkeypatch, valid=0, missing=1, salvage=1,
        old_contract=wire.STRUCTURED_OUTPUT, missing_criterion_count=120)
    path = next((runner.root / 'artifacts' / old[0].key).rglob('attempt-002.response.json'))
    raw = json.loads(path.read_text())
    value = json.loads(raw['generation']['text'])
    if damage == 'level-out-of-bounds': value['criteria_text'] = value['criteria_text'].replace('0|0|', '0|2|', 1)
    elif damage == 'empty-overall': value['overall_reasoning'] = ''
    elif damage == 'wrong-provider': raw['generation']['provider'] = 'openai'
    elif damage == 'wrong-model': raw['generation']['requested_model'] = 'another-model'
    else: raw['request']['execution']['structured_output_contract'] = wire.V7_STRUCTURED_OUTPUT
    raw['generation']['text'] = json.dumps(value)
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(judge_module, '_generate_response', lambda *a, **k: pytest.fail('provider call'))
    if damage in {'wrong-provider', 'wrong-model'}:
        with pytest.raises(RuntimeError, match='response model differs'):
            runner.preflight()
    else:
        runner.preflight()
        assert not runner._saved_response_replays


def test_native_v8_replay_publication_failure_never_enters_provider_retries(tmp_path, monkeypatch):
    runner, _, _ = _fixture_panel(tmp_path, monkeypatch, valid=0, missing=1, salvage=1,
        old_contract=wire.STRUCTURED_OUTPUT, missing_criterion_count=120)
    monkeypatch.setattr(judge_module, '_generate_response', lambda *a, **k: pytest.fail('provider call'))
    runner.preflight()
    _prepare_output(runner)
    job = runner._prepared.unique_jobs[0]
    publish = judge_module.RubricScoreJudge._publish
    attempts = []
    def fail_once(self, **kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise OSError('fixture publication failure')
        return publish(self, **kwargs)
    monkeypatch.setattr(judge_module.RubricScoreJudge, '_publish', fail_once)
    with pytest.raises(OSError, match='fixture publication failure'):
        runner._run_job(job)
    # The already decoded saved response is durable before publication retries.
    record = runner._run_job(job)
    assert record['engine_execution']['structured_output_contract'] == wire.STRUCTURED_OUTPUT
    assert len(attempts) == 2
