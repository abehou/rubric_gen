"""Provider-free fixtures for the Results20 duplicate-block failure and repair."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, ValidationError

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.submission_revision.evaluation import indexed_rubric as wire
from rubric_gen.submission_revision.evaluation import jobs, resume, rubric_judge as judge_module
from rubric_gen.submission_revision.evaluation.rubric_score import (
    _rubric_score_attempt_id, _rubric_score_assignment_reference_sha256,
)
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricGeneration, FullRubricJudgeError
from test_evaluation_rubric_judge import _many_criterion_rubric
from test_revision_evaluation import _target
from test_runtime_reliability import _wire, _strings, _text


def _keyed(items):
    value = _wire(items)
    if 'full_blocks' in value['criteria']:
        value['criteria']['full_blocks'] = {f"block_{block['block_index']}": block['values']
                                          for block in value['criteria']['full_blocks']}
    return value


@pytest.mark.parametrize('count', [65, 86, 87, 92, 120, 145, 255, 403, 872])
@pytest.mark.parametrize('damage', ['missing', 'extra', 'wrong-index', 'missing-tail', 'bad-tail', 'bad-tree'])
def test_keyed_schema_and_decoder_require_every_block_and_leaf(count, damage):
    value = _keyed(['0|evidence'] * count)
    blocks = value['criteria']['full_blocks']
    if damage == 'missing': del blocks['block_0']
    elif damage == 'extra': blocks['block_extra'] = blocks['block_0']
    elif damage == 'wrong-index': blocks['0'] = blocks.pop('block_0')
    elif damage == 'missing-tail': del value['criteria']['tail']
    elif damage == 'bad-tail': value['criteria']['tail'] = {}  # even a single-leaf tail is mandatory
    else: blocks['block_0'] = '0|evidence'
    schema = judge_module._anthropic_rubric_score_schema(wire.output_schema(count, contract=wire.V6_STRUCTURED_OUTPUT))
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(value)
    with pytest.raises(FullRubricJudgeError):
        wire.decode_output(json.dumps(value), count, contract=wire.V6_STRUCTURED_OUTPUT)


def test_duplicate_keys_rejected_before_json_object_can_collapse_them():
    value = _keyed(['0|evidence'] * 92)
    tree = json.dumps(value['criteria']['full_blocks']['block_0'])
    text = json.dumps(value).replace('"block_0": ' + tree, '"block_0": ' + tree + ', "block_0": ' + tree)
    with pytest.raises(FullRubricJudgeError, match='duplicate JSON key'):
        wire.decode_output(text, 92, contract=wire.V6_STRUCTURED_OUTPUT)


@pytest.mark.parametrize('leaf', ['x', 'y', 'placeholder', '', '0|', '0| \n ', ':0|evidence', '01|evidence'])
def test_v6_leaf_pattern_enforces_existing_decimal_and_nonempty_reason_contract(leaf):
    value = _keyed([leaf])
    with pytest.raises(ValidationError):
        Draft202012Validator(wire.output_schema(1, contract=wire.V6_STRUCTURED_OUTPUT)).validate(value)
    with pytest.raises(FullRubricJudgeError):
        judge_module.parse_rubric_score_output(wire.decode_output(json.dumps(value), 1, contract=wire.V6_STRUCTURED_OUTPUT),
                                             {'criterion_1': {'A': 1, 'B': 0}})


@pytest.mark.parametrize('leaf', ['0|reason', '12| multiline\nreason ', '1|contains | delimiter'])
def test_leaf_pattern_allows_existing_reason_text(leaf):
    Draft202012Validator(wire.output_schema(1, contract=wire.V6_STRUCTURED_OUTPUT)).validate(_keyed([leaf]))


def test_criterion_specific_level_bounds_and_overall_reasoning_still_fail():
    for leaf, reasoning in [('3|evidence', 'overall'), ('0|evidence', '')]:
        value = _keyed([leaf]); value['overall_reasoning'] = reasoning
        with pytest.raises(FullRubricJudgeError):
            judge_module.parse_rubric_score_output(wire.decode_output(json.dumps(value), 1, contract=wire.V6_STRUCTURED_OUTPUT),
                                                 {'criterion_1': {'A': 1, 'B': 0}})


@pytest.mark.parametrize('count', [92, 255])
def test_explicit_v5_replay_accepts_only_identical_redundant_blocks(count):
    items = [f'{i % 2}|evidence {i}' for i in range(count)]
    original = _wire(items)
    duplicate = deepcopy(original)
    duplicate['criteria']['full_blocks'].append(deepcopy(duplicate['criteria']['full_blocks'][0]))
    # The actual v5 provider schema accepts the observed erroneous output.
    Draft202012Validator(wire.output_schema(count, contract=wire.V5_STRUCTURED_OUTPUT)).validate(duplicate)
    with pytest.raises(FullRubricJudgeError):
        wire.decode_output(json.dumps(duplicate), count, contract=wire.V5_STRUCTURED_OUTPUT)
    assert wire.replay_saved_v5_output(json.dumps(duplicate), count) == wire.decode_output(
        json.dumps(original), count, contract=wire.V5_STRUCTURED_OUTPUT)
    assert wire.decode_output(json.dumps(_keyed(items)), count, contract=wire.V6_STRUCTURED_OUTPUT) == wire.decode_output(
        json.dumps(original), count, contract=wire.V5_STRUCTURED_OUTPUT)
    duplicate['criteria']['full_blocks'][-1]['values']['left'] = '1|conflicting evidence'
    with pytest.raises(FullRubricJudgeError, match='conflicting'):
        wire.replay_saved_v5_output(json.dumps(duplicate), count)
    missing = deepcopy(original); missing['criteria']['full_blocks'].pop()
    with pytest.raises(FullRubricJudgeError):
        wire.replay_saved_v5_output(json.dumps(missing), count)


def _fixture_panel(tmp_path, monkeypatch, *, valid=760, missing=140, salvage=2, sol=0,
                   old_contract=wire.V5_STRUCTURED_OUTPUT, missing_criterion_count=65,
                   saved_v8_attempts=None):
    assert missing == 0 or old_contract in {wire.V5_STRUCTURED_OUTPUT, wire.STRUCTURED_OUTPUT}
    target = _target(tmp_path)
    (tmp_path / 'instruction.md').write_text('Implement the task.')
    small = tmp_path / 'small.txt'; small.write_text(_many_criterion_rubric(1))
    large = tmp_path / 'large.txt'; large.write_text(_many_criterion_rubric(missing_criterion_count))
    exp = SimpleNamespace(protocol={}, outcome_audit={'models': ['gpt-5.6-sol', 'claude-opus-5'],
        'rubric_score_max_calls': 10000, 'rubric_score_max_request_bytes': 10**12,
        'rubric_score_max_output_tokens': 10**12})
    runner = RubricScoreRunner(jobs.EvaluationConfig(experiment=exp, study_dir=tmp_path / 'study',
        paraphrase_dir=tmp_path / 'pool', output_dir=tmp_path / 'audit', max_concurrency=1, resume=True), (target,))
    native_judge = runner._judge_for_job
    reviews = {sha256_text(f'evidence {i}'): f'evidence {i}' for i in range(valid + missing + sol)}

    def judge_for(job):
        judge = native_judge(job)
        judge.review_inputs = lambda _: (reviews[job.review_input_sha256], 'answer')
        return judge

    monkeypatch.setattr(runner, '_judge_for_job', judge_for)
    planned, original, entries = [], [], []
    for i in range(valid + missing + sol):
        completed = i < valid or i >= valid + missing
        model = 'gpt-5.6-sol' if i >= valid + missing else 'claude-opus-5'
        review = f'evidence {i}'
        job = jobs.RubricScoreJob(target=target, model=model, artifact='initial',
            rubric_path=small if completed else large, roles=(), generation_bindings=(),
            grading_identity={}, review_input_sha256=sha256_text(review), answer_input_sha256=sha256_text('answer'),
            evaluation_implementation_sha256=jobs._evaluation_implementation_sha256())
        current = judge_for(job).scoring_identity()
        planned.append(replace(job, grading_identity=current))
        old = replace(job, grading_identity={**current, 'scoring_implementation_sha256': 'a' * 64},
                      evaluation_implementation_sha256='b' * 64)
        original.append(old)
        judge = judge_for(old)
        spec = judge_module.build_rubric_score_run_spec(rubric_text=judge.rubric.text,
            review_text=review, answer_text='answer', requested_model=model,
            seed=judge._grading_seed(review, 'answer'), indexed_contract=old_contract)
        entry = jobs._rubric_score_plan_entry(job=old, judge=judge, review_text=review, answer_text='answer',
            shape=judge_module.full_rubric_cost_shape(judge.rubric.text, review_text=review, answer_text='answer').as_json())
        entry['grading_identity'] = old.grading_identity
        entries.append(entry)
        generation = FullRubricGeneration(text=json.dumps((_wire if old_contract == wire.V5_STRUCTURED_OUTPUT else _keyed if old_contract == wire.V6_STRUCTURED_OUTPUT else _strings if old_contract == wire.V7_STRUCTURED_OUTPUT else _text)(['0|evidence'] * spec.criterion_count)
            if model.startswith('claude') else {'criteria': [{'level_index': 0, 'reason': 'evidence'}],
                                              'overall_reasoning': 'fixture reasoning'}),
            provider=spec.provider, requested_model=model, effective_model=model, response_id=f'original-{i}',
            request_parameters=judge_module._request_parameters(spec), usage={'output_tokens': 200})
        attempt_id = _rubric_score_attempt_id(old)
        root = judge._evaluation_root(old.submission, attempt_id)
        identity = {'scoring_identity': old.grading_identity, 'review_input_sha256': old.review_input_sha256,
                    'answer_input_sha256': old.answer_input_sha256}
        if completed:
            records = judge_module._records_from_generation(spec, generation, rubric_text=judge.rubric.text)
            judge._publish(root=root, records=records, scoring_identity=old.grading_identity,
                           review_text=review, answer_text='answer')
            record = {**jobs._rubric_score_judgment_identity(old), 'score': records.score,
                'attempt_id': attempt_id, 'validation_path': str(root / 'score_validation.json'),
                'evaluation_path': str(root / 'evaluation.json'), 'engine_execution': spec.as_json()}
            runner.output.write_json(('records', f'{old.key}.json'), record)
        else:
            attempts = root.parent / f'{attempt_id}.attempts'; attempts.mkdir(parents=True)
            for number in range(1, 4):
                if old_contract == wire.V5_STRUCTURED_OUTPUT:
                    response = _wire(['0|evidence'] * spec.criterion_count)
                    duplicate = deepcopy(response['criteria']['full_blocks'][0])
                    if not (i < valid + salvage and number == 2):
                        duplicate['values']['left']['left']['left']['left']['left']['left'] = '1|different'
                    response['criteria']['full_blocks'].append(duplicate)
                else:
                    complete_attempts = saved_v8_attempts if saved_v8_attempts is not None else [(2,)] * salvage
                    complete = i < valid + salvage and number in complete_attempts[i - valid]
                    count = spec.criterion_count if complete else spec.criterion_count - 1
                    response = _text(['0|evidence | retained pipe'] * count)
                    # The production tail contains complete one-line pipe rows,
                    # and incomplete outputs in both pipe and newline forms.
                    if complete or (i - valid + number) % 2 == 0:
                        response['criteria_text'] = response['criteria_text'].replace('\n', '|')
                raw = {'request': {'execution': spec.as_json(),
                                  'payload': judge_module.rubric_score_payload(judge.rubric.text, review, 'answer'),
                                  'schema': wire.output_schema(spec.criterion_count, contract=old_contract)},
                       'generation': {**generation.__dict__, 'text': json.dumps(response)}}
                (attempts / f'attempt-{number:03d}.response.json').write_text(json.dumps(raw))
                error = {'identity': identity, 'attempt': number, 'remote_completion': 'unknown',
                         'failure_category': 'invalid_response', 'error': (
                             'FullRubricJudgeError: count-safe block count does not exactly match the rubric'
                             if old_contract == wire.V5_STRUCTURED_OUTPUT else
                             f'FullRubricJudgeError: rubric criteria_text must contain exactly {spec.criterion_count} criterion lines')}
                (attempts / f'attempt-{number:03d}.json').write_text(json.dumps(error))
                (root.parent / f'failed-attempt-{number:03d}.json').write_text(json.dumps(error))
    manifest = {'kind': 'fixture', 'implementation_identity': {'evaluation_sha256': 'b' * 64},
                'predispatch_plan': {'jobs': entries},
                'assignment_reference_identity_sha256': _rubric_score_assignment_reference_sha256(tuple(original))}
    runner.output.write_json(('manifest.json',), manifest)
    monkeypatch.setattr(runner, '_jobs', lambda targets: tuple(planned))
    return runner, planned, original


@pytest.mark.parametrize('salvage', [0, 2])
def test_native_resume_760_valid_140_exhausted_preserves_records_and_attempts(tmp_path, monkeypatch, salvage):
    runner, planned, original = _fixture_panel(tmp_path, monkeypatch, salvage=salvage, sol=3)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in runner.root.rglob('*') if p.is_file()}
    calls = []

    def generate(spec, *, payload, schema):
        assert spec.provider == 'anthropic'
        calls.append(json.loads(payload)['artifact_evidence']['workspace_review'])
        assert spec.as_json()['structured_output_contract'] == wire.STRUCTURED_OUTPUT
        return FullRubricGeneration(text=json.dumps(_text(['0|evidence'] * spec.criterion_count)),
            provider=spec.provider, requested_model=spec.requested_model, effective_model=spec.requested_model,
            response_id='new-fixture', request_parameters=judge_module._request_parameters(spec), usage={})

    monkeypatch.setattr(judge_module, '_generate_response', generate)
    runner.preflight()
    prepared = runner._prepared
    assert len(runner._reused_records) == 763
    assert len(runner._saved_response_replays) == salvage
    assert len([j for j in prepared.unique_jobs if j.key not in runner._reused_records]) == 140
    assert calls == []  # Native preparation has no provider work or publication.
    prior = json.loads((runner.root / 'manifest.json').read_text())
    current = {**prior, 'predispatch_plan': prepared.predispatch_plan,
               'implementation_identity': jobs._rubric_score_implementation_identity(prepared.unique_jobs),
               'assignment_reference_identity_sha256': _rubric_score_assignment_reference_sha256(prepared.jobs)}
    resume.prepare_stage_output(runner.output, current, True, prepared.jobs)
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in before.items())
    results = [runner._run_job(job) for job in prepared.unique_jobs]
    assert len(results) == 903 and len(calls) == 140 - salvage
    assert set(calls) == {f'evidence {i}' for i in range(760 + salvage, 900)}
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in before.items())
    for job in prepared.unique_jobs:
        if job.key in runner._saved_response_replays:
            record = json.loads((runner.root / 'records' / f'{job.key}.json').read_text())
            assert record['grading_identity'] == job.grading_identity
            assert record['engine_execution']['structured_output_contract'] == wire.V5_STRUCTURED_OUTPUT
            usage = json.loads((runner.root / 'artifacts' / job.key / 'evaluations' / job.submission.name /
                                job.grading_identity['rendered_rubric_sha256'] / record['attempt_id'] / 'usage.json').read_text())
            assert usage['local_response_replay']['producer_identity']['scoring_identity']['scoring_implementation_sha256'] == 'a' * 64
    # Another native resume validates both representations and buys nothing.
    runner._prepared = None
    runner.preflight()
    assert len(runner._reused_records) == 903 and not runner._saved_response_replays
    for job in runner._prepared.unique_jobs:
        runner._run_job(job)
    assert len(calls) == 140 - salvage


@pytest.mark.parametrize('field,value', [('reasoning_effort', 'high'), ('max_output_tokens_per_call', 9000),
    ('requested_model', 'claude-other'), ('system_prompt_sha256', 'f' * 64)])
def test_old_valid_record_rejects_changed_scientific_execution(tmp_path, monkeypatch, field, value):
    runner, planned, old = _fixture_panel(tmp_path, monkeypatch, valid=1, missing=0, salvage=0)
    record_path = runner.root / 'records' / f'{old[0].key}.json'
    record = json.loads(record_path.read_text())
    metadata_path = runner.root / 'artifacts' / old[0].key / 'evaluations' / old[0].submission.name / old[0].grading_identity['rendered_rubric_sha256'] / record['attempt_id'] / 'metadata.json'
    metadata = json.loads(metadata_path.read_text())
    metadata['engine_execution'][field] = value
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match='saved rubric (request setting|scientific instructions)'):
        runner.preflight()


@pytest.mark.parametrize('field', ['payload', 'schema', 'max_output_tokens_per_call', 'system_prompt_sha256'])
@pytest.mark.parametrize('contract', [wire.V5_STRUCTURED_OUTPUT, wire.STRUCTURED_OUTPUT])
def test_local_replay_requires_exact_saved_request(tmp_path, monkeypatch, field, contract):
    runner, planned, old = _fixture_panel(tmp_path, monkeypatch, valid=0, missing=1, salvage=1, old_contract=contract)
    raw_path = next((runner.root / 'artifacts' / old[0].key).rglob('attempt-002.response.json'))
    raw = json.loads(raw_path.read_text())
    if field in {'payload', 'schema'}:
        raw['request'][field] = 'changed'
    else:
        raw['request']['execution'][field] = 'changed'
    raw_path.write_text(json.dumps(raw))
    with pytest.raises(RuntimeError, match='terminal response request changed'):
        runner.preflight()


def test_repaired_attempt_budget_remains_bounded_across_resumes(tmp_path, monkeypatch):
    runner, planned, old = _fixture_panel(tmp_path, monkeypatch, valid=0, missing=1, salvage=0)
    calls = []
    def fail(spec, **kwargs):
        calls.append(spec)
        raise FullRubricJudgeError('fixture invalid response')
    monkeypatch.setattr(judge_module, '_generate_response', fail)
    monkeypatch.setattr(judge_module.time, 'sleep', lambda _: None)
    runner.preflight()
    current = runner._prepared.unique_jobs[0]
    assert current.key != old[0].key
    for _ in range(2):
        with pytest.raises(RuntimeError, match='failed after 3 attempts'):
            runner._run_job(current)
    assert len(calls) == 3
    assert len(list((runner.root / 'artifacts' / old[0].key).rglob('failed-attempt-*.json'))) == 3


@pytest.mark.parametrize('contract', [wire.V5_STRUCTURED_OUTPUT, wire.V6_STRUCTURED_OUTPUT, wire.V7_STRUCTURED_OUTPUT, wire.STRUCTURED_OUTPUT])
def test_native_resume_preserves_each_recorded_wire_provenance(tmp_path, monkeypatch, contract):
    runner, _, old = _fixture_panel(tmp_path, monkeypatch, valid=1, missing=0, salvage=0, old_contract=contract)
    before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in runner.root.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError('valid saved judgments must not invoke providers')
    monkeypatch.setattr(judge_module, '_generate_response', forbidden)
    runner.preflight()
    assert len(runner._reused_records)==1
    record=runner._run_job(runner._prepared.unique_jobs[0])
    assert record['engine_execution']['structured_output_contract']==contract
    assert all((p.read_bytes(),p.stat().st_mtime_ns)==value for p,value in before.items())
