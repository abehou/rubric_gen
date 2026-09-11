"""No-provider replay of long streams, indexed output, and missing-only resume."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest
from jsonschema import Draft202012Validator

from rubric_gen.runtime import provider_streams
from rubric_gen.submission_revision.evaluation import indexed_rubric, rubric_judge
from rubric_gen.submission_revision.judging import executor as executor_module
from rubric_gen.submission_revision.judging import full_rubric_judge, full_rubric_protocol
from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricJudgeError
from test_full_rubric_judge import _attestation, _executor, _resolved_rubric, _spec
from test_evaluation_rubric_judge import RUBRIC, _many_criterion_rubric


def _sse(event):
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()


class TimedNetworkStream(httpx.SyncByteStream):
    """Fake socket reads enforce the actual SDK-provided HTTP read timeout."""
    def __init__(self, request, events):
        self.request, self.events = request, events
        self.elapsed = 0
        self.closed = False

    def __iter__(self):
        read_timeout = self.request.extensions['timeout']['read']
        for delay, chunk in self.events:
            if delay >= read_timeout:
                self.elapsed += read_timeout
                raise httpx.ReadTimeout('simulated network inactivity', request=self.request)
            self.elapsed += delay
            yield chunk

    def close(self):
        self.closed = True


def _events(provider, text, *, gap, completed):
    if provider == 'anthropic':
        first = dict(type='message_start', message=dict(id='msg_fixture', type='message',
            role='assistant', content=[], model='claude-opus-5', stop_reason=None,
            stop_sequence=None, usage=dict(input_tokens=11, output_tokens=0)))
        events = [(0, _sse(first)), (0, _sse(dict(type='content_block_start', index=0,
            content_block=dict(type='text', text=''))))]
        events += [(gap, _sse(dict(type='ping')))] * 4
        events += [(0, _sse(dict(type='content_block_delta', index=0,
            delta=dict(type='text_delta', text=text)))),
            (0, _sse(dict(type='content_block_stop', index=0))),
            (0, _sse(dict(type='message_delta', delta=dict(stop_reason='end_turn',
                stop_sequence=None), usage=dict(output_tokens=17))))]
        if completed:
            events.append((0, _sse(dict(type='message_stop'))))
        return events
    response = dict(id='resp_fixture', object='response', created_at=0,
        status='completed', model='gpt-5.6-sol', output=[dict(type='message',
        id='msg_fixture', role='assistant', status='completed', content=[dict(
        type='output_text', text=text, annotations=[])])],
        usage=dict(input_tokens=11, output_tokens=17, total_tokens=28))
    events = [(gap, b': keepalive\n\n')] * 4
    if completed:
        events.append((0, _sse(dict(type='response.completed', response=response))))
    return events


def _install_network(monkeypatch, provider, text, *, gap=120, completed=True):
    requests, streams, clients = [], [], []
    module = anthropic if provider == 'anthropic' else openai
    name = 'Anthropic' if provider == 'anthropic' else 'OpenAI'
    constructor = getattr(module, name)

    def handle(request):
        requests.append(request)
        stream = TimedNetworkStream(request, _events(provider, text, gap=gap, completed=completed))
        streams.append(stream)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)

    def client(**kwargs):
        http = httpx.Client(transport=httpx.MockTransport(handle))
        clients.append(http)
        assert kwargs['max_retries'] == 0
        return constructor(**kwargs, http_client=http)

    monkeypatch.setattr(module, name, client)
    monkeypatch.setenv('ANTHROPIC_API_KEY' if provider == 'anthropic' else 'OPENAI_API_KEY', 'fake-key')
    return requests, streams, clients


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
@pytest.mark.parametrize('audit', [True, False])
def test_eight_minute_stream_preserves_request_and_usage(monkeypatch, provider, audit):
    model = 'claude-opus-5' if provider == 'anthropic' else 'gpt-5.6-sol'
    canonical = dict(criteria={'criterion_1': dict(level='A', reason='evidence')},
                     overall_reasoning='evidence')
    wire = canonical
    if audit:
        wire = dict(criteria={'tail': '0|evidence'} if provider == 'anthropic' else
                    [dict(level_index=0, reason='evidence')], overall_reasoning='evidence')
    requests, streams, clients = _install_network(monkeypatch, provider, json.dumps(wire))
    grade = rubric_judge.grade_rubric_score if audit else full_rubric_judge.grade_full_rubric
    result = grade(rubric_text=RUBRIC, review_text='complete evidence', answer_text='answer',
                   requested_model=model, seed=31)
    assert result.score == 100
    assert result.evaluation['full_rubric_structured']['raw_report'] == canonical
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body['stream'] is True and body['model'] == model
    assert body['max_tokens' if provider == 'anthropic' else 'max_output_tokens'] == 4096
    assert body.get('output_config', {}).get('effort') == ('low' if provider == 'anthropic' else None)
    if provider == 'openai':
        assert body['store'] is False and body['reasoning'] == {'effort': 'none'}
        assert body['temperature'] == 0
    else:
        assert 'temperature' not in body
    payload = json.loads(body['messages' if provider == 'anthropic' else 'input'][-1]['content'])
    assert payload['rubric_text'] == RUBRIC
    assert payload['artifact_evidence'] == {'workspace_review': 'complete evidence', 'final_answer': 'answer'}
    usage = result.usage['call']
    assert usage['raw_usage']['input_tokens'] == 11 and usage['raw_usage']['output_tokens'] == 17
    assert usage['response_id'] == ('msg_fixture' if provider == 'anthropic' else 'resp_fixture')
    assert usage['effective_model'] == model
    assert usage['request_parameters']['timeout_semantics'] == 'network-inactivity'
    assert usage['request_parameters']['stream'] is True
    assert streams[0].elapsed == 480 and streams[0].closed and clients[0].is_closed
    print(f'{provider} {"audit" if audit else "revision"}: 480s response, 120s activity gaps, one call, success')


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
@pytest.mark.parametrize('gap', [300, 301])
def test_inactivity_timeout_uses_sdk_read_timeout(monkeypatch, provider, gap):
    requests, streams, clients = _install_network(monkeypatch, provider, '{}', gap=gap)
    invoke = provider_streams.anthropic_response if provider == 'anthropic' else provider_streams.openai_response
    error = anthropic.APITimeoutError if provider == 'anthropic' else openai.APITimeoutError
    with pytest.raises(error):
        invoke(api_key='fake-key', timeout=300, model='fixture', max_tokens=10, messages=[]) if provider == 'anthropic' else invoke(
            api_key='fake-key', timeout=300, model='fixture')
    assert len(requests) == 1 and streams[0].elapsed == 300
    assert streams[0].closed and clients[0].is_closed
    print(f'{provider}: {gap}s inactivity fails at 300s; no SDK retry')


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
def test_incomplete_stream_is_never_a_judgment(monkeypatch, provider):
    _, streams, clients = _install_network(monkeypatch, provider, '{}', gap=1, completed=False)
    with pytest.raises(RuntimeError, match='stream ended without'):
        if provider == 'anthropic':
            provider_streams.anthropic_response(api_key='fake', timeout=300, model='fixture', max_tokens=10, messages=[])
        else:
            provider_streams.openai_response(api_key='fake', timeout=300, model='fixture')
    assert streams[0].closed and clients[0].is_closed


def _wire(items):
    def tree(values):
        if len(values) == 1:
            return values[0]
        middle = len(values) // 2
        return dict(left=tree(values[:middle]), right=tree(values[middle:]))
    count, tail = divmod(len(items), 64)
    criteria = {}
    if count:
        criteria['full_blocks'] = [dict(block_index=i, values=tree(items[64*i:64*i+64])) for i in range(count)]
    if tail:
        criteria['tail'] = tree(items[count*64:])
    return dict(criteria=criteria, overall_reasoning='fixture reasoning')


@pytest.mark.parametrize('count', [1, 2, 63, 64, 65, 128, 145, 872, 1000])
def test_indexed_round_trip_order_levels_and_scores(count):
    rubric = _many_criterion_rubric(count).replace('A=1 B=0', 'A=2 B=-1')
    levels = rubric_judge.parse_rubric_levels_strict(rubric)
    # Unique evidence and alternating levels expose any swapped/duplicated leaf.
    items = [dict(level_index=i % 2, reason=f'evidence {i}|kept') for i in range(count)]
    wire = _wire([f"{v['level_index']}|{v['reason']}" for v in items])
    schema = indexed_rubric.output_schema(count)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(wire)
    assert rubric_judge._anthropic_rubric_score_schema(schema) == schema
    if count >= 64:
        wire['criteria']['full_blocks'].reverse()
    decoded = indexed_rubric.decode_output(json.dumps(wire), count)
    actual = rubric_judge.parse_rubric_score_output(decoded, levels)
    expected = rubric_judge.parse_rubric_score_output(json.dumps(dict(criteria=items,
        overall_reasoning='fixture reasoning')), levels)
    assert actual == expected and list(actual['criteria']) == list(levels)
    spec = rubric_judge.build_rubric_score_run_spec(rubric_text=rubric, review_text='evidence',
        answer_text='', requested_model='claude-opus-5', seed=31)
    usage = full_rubric_protocol.FullRubricGeneration(text='', provider=spec.provider,
        requested_model=spec.requested_model, effective_model=spec.requested_model,
        response_id='fixture', request_parameters=rubric_judge._request_parameters(spec), usage={}).usage_record()
    a = full_rubric_protocol.records_from_report(rubric_text=rubric, raw_report=actual, spec=spec, call_usage=usage)
    b = full_rubric_protocol.records_from_report(rubric_text=rubric, raw_report=expected, spec=spec, call_usage=usage)
    assert a == b
    assert spec.schema_bytes == rubric_judge._canonical_json_bytes(schema)
    payload = rubric_judge.rubric_score_payload(rubric, 'evidence', '')
    assert spec.request_content_bytes_per_call == (len(payload.encode()) + spec.schema_bytes +
        len(rubric_judge._system_prompt('anthropic').encode()))
    if count == 872:
        print('872 indexed criteria round-trip in canonical order; signed/normalized scores identical')


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'extra', 'bool', 'negative', 'wrong-tree', 'tail', 'bad-index', 'empty-reason'])
def test_invalid_indexed_response_rejected(damage):
    wire = _wire(['0|evidence'] * 145)
    blocks = wire['criteria']['full_blocks']
    if damage == 'missing': blocks.pop()
    elif damage == 'duplicate': blocks[1]['block_index'] = 0
    elif damage == 'extra': blocks.append(deepcopy(blocks[0]))
    elif damage == 'bool': blocks[0]['block_index'] = False
    elif damage == 'negative': blocks[0]['block_index'] = -1
    elif damage == 'wrong-tree': blocks[0]['values'] = '0|evidence'
    elif damage == 'tail': del wire['criteria']['tail']
    else:
        items = ['0|evidence'] * 145
        items[0] = '01|evidence' if damage == 'bad-index' else '0| '
        wire = _wire(items)
    with pytest.raises(FullRubricJudgeError):
        rubric_judge.parse_rubric_score_output(indexed_rubric.decode_output(json.dumps(wire), 145),
            {f'criterion_{i}': {'A': 1, 'B': 0} for i in range(145)})


def test_duplicate_json_keys_rejected():
    with pytest.raises(FullRubricJudgeError, match='duplicate JSON key'):
        indexed_rubric.decode_output('{"criteria":{"tail":"0|a","tail":"1|b"},"overall_reasoning":"x"}', 1)


@pytest.mark.parametrize('duration', [480, 3601])
def test_outer_watchdog_allows_long_stream_but_bounds_wedge(tmp_path, monkeypatch, duration):
    executor = _executor(tmp_path)
    output_dir = tmp_path / 'output'
    output_dir.mkdir()
    output = SimpleNamespace(path=output_dir)
    executor.artifacts = SimpleNamespace(
        validate_output_directory=lambda output: None,
        unlink_output_file=lambda *args: None,
        write_output_text=lambda output, name, text: (output.path / name).write_text(text),
        write_output_bytes=lambda output, name, data: (output.path / name).write_bytes(data),
    )
    spec = _spec()
    monkeypatch.setattr(executor, 'score_input_attestation', lambda **kwargs: _attestation(spec))
    monkeypatch.setattr(executor, 'build_score_validation_from_bytes', lambda *args: {'score': 100, 'normalized_score': 1})

    def run(command, **kwargs):
        assert kwargs['timeout'] == 3600
        if duration >= kwargs['timeout']:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'partial stream')
        logs = Path(command[command.index('--output-dir') + 1])
        for name in ('reward.json', 'evaluation.json', 'usage.json'):
            (logs / name).write_text('{}')
        return subprocess.CompletedProcess(command, 0, stdout='completed')

    monkeypatch.setattr(executor_module.subprocess, 'run', run)
    result = executor.execute_with_output(Path(full_rubric_judge.__file__), _resolved_rubric(tmp_path),
        output, 'workspace', '', attempt=SimpleNamespace(target=SimpleNamespace()))
    assert result['exit_code'] == (0 if duration < 3600 else 124)
    if duration > 3600:
        assert '3600 seconds' in (output_dir / 'stdout.txt').read_text()


def test_resume_preserves_failed_attempts_and_retry_budget(tmp_path, monkeypatch):
    from rubric_gen.artifacts.hashing import sha256_text
    from rubric_gen.benchmarks import SubmissionBenchmarkId
    from rubric_gen.submission_revision.judge import FrozenRubric, SubmissionJudgeConfig
    from test_evaluation_rubric_judge import _records

    task = tmp_path / 'task'
    task.mkdir()
    submission = tmp_path / 's000'
    submission.mkdir()
    rubric_path = task / 'rubric.txt'
    rubric_path.write_text(RUBRIC)
    judge = rubric_judge.RubricScoreJudge(SubmissionJudgeConfig(task_dir=task,
        experiment_dir=tmp_path / 'audit', benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        review='trace', judge_model='claude-opus-5', rubric_name=None, rubric_set=None,
        rubric_path=rubric_path, max_review_chars=None), FrozenRubric(text=RUBRIC,
        sha256=sha256_text(RUBRIC), source='rubric-path', rubric_set_id=None,
        rubric_id=None, structured_rubric_sha256=None, manifest_sha256=None))
    judge._review_delegate = SimpleNamespace(review_inputs=lambda _: ('workspace', 'answer'))
    calls = []

    def grade(**kwargs):
        calls.append(kwargs)
        if len(calls) <= 4:
            raise TimeoutError(f'failure {len(calls)}')
        return _records(**kwargs)

    monkeypatch.setattr(rubric_judge, 'grade_rubric_score', grade)
    attempt_id = 'a' * 32
    with pytest.raises(RuntimeError, match='failed after 3 attempts'):
        judge.evaluate(submission, attempt_id)
    assert len(calls) == 3
    parent = judge._evaluation_root(submission, attempt_id).parent
    before = {p.name: p.read_bytes() for p in parent.glob('failed-attempt-*')}
    assert len(before) == 3
    with pytest.raises(RuntimeError, match='failed after 3 attempts'):
        judge.evaluate(submission, attempt_id)
    assert len(calls) == 3  # Resume cannot reset the exhausted logical budget.
    assert {name: (parent / name).read_bytes() for name in before} == before


def test_resume_3333_completed_schedules_only_27_missing(tmp_path, monkeypatch):
    """Use the production resume branch and record validator with fake judgments."""
    from rubric_gen.submission_revision.evaluation import jobs as jobs_module
    from rubric_gen.submission_revision.evaluation import rubric_score as stage_module
    from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig, RubricScoreJob
    from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
    from rubric_gen.submission_revision.judge import SCORING_IDENTITY_KEYS
    from test_revision_evaluation import _target

    target = _target(tmp_path)
    (tmp_path / 'instruction.md').write_text('Complete the task.')
    submission = target.initial_submission
    workspace = submission / 'workspace'
    workspace.mkdir(parents=True)
    (workspace / 'trace.md').write_text('trace')
    (workspace / 'answer.txt').write_text('answer')
    (submission / 'snapshot.json').write_text(json.dumps({'workspace_sha256': 'c' * 64}))
    rubric_path = tmp_path / 'rubric.txt'
    rubric_path.write_text(target.initial_generation.rubric.content)
    grading = dict.fromkeys(SCORING_IDENTITY_KEYS)
    runner = RubricScoreRunner(EvaluationConfig(experiment=SimpleNamespace(protocol={}, outcome_audit={}),
        study_dir=tmp_path / 'study', paraphrase_dir=tmp_path / 'paraphrases',
        output_dir=tmp_path / 'output', max_concurrency=1, resume=True), (target,))
    calls, dispatched = [], []
    jobs = [RubricScoreJob(target=target, model='fixture', artifact='initial', rubric_path=rubric_path,
        roles=(), generation_bindings=(), grading_identity=grading,
        review_input_sha256=f'{i:064x}', answer_input_sha256='5' * 64,
        evaluation_implementation_sha256='6' * 64) for i in range(3360)]
    assert len({job.key for job in jobs}) == 3360

    def fixture(job):
        directory = runner.output.ensure_directory('artifacts', job.key, 'evaluations')
        return SimpleNamespace(score_validation_path=directory / 'validation.json',
                               evaluation_path=directory / 'evaluation.json')

    def publish(job):
        artifacts = fixture(job)
        validation = {**grading, 'score': 50, 'review_input_sha256': job.review_input_sha256,
            'answer_input_sha256': job.answer_input_sha256, 'engine_execution': {'fixture': True}}
        artifacts.score_validation_path.write_text(json.dumps(validation))
        artifacts.evaluation_path.write_text('{}')
        return artifacts

    def evaluate(job):
        calls.append(job.key)
        return publish(job)

    monkeypatch.setattr(runner, '_judge_for_job', lambda job: SimpleNamespace(
        validate=lambda *_: fixture(job), evaluate=lambda *_: evaluate(job)))
    monkeypatch.setattr(runner, '_assert_current_dispatch', lambda job, judge: dispatched.append(job.key))
    before = {}
    for job in jobs[:3333]:
        artifacts = publish(job)
        record = {**jobs_module._rubric_score_judgment_identity(job), 'score': 50,
            'attempt_id': stage_module._rubric_score_attempt_id(job),
            'validation_path': str(artifacts.score_validation_path),
            'evaluation_path': str(artifacts.evaluation_path), 'engine_execution': {'fixture': True}}
        path = runner.output.write_json(('records', f'{job.key}.json'), record)
        for p in (path, artifacts.score_validation_path, artifacts.evaluation_path):
            before[p] = (p.read_bytes(), p.stat().st_mtime_ns)
    # A retryable missing judgment can have prior failed-attempt evidence.
    failed = runner.output.ensure_directory('artifacts', jobs[-1].key, 'evaluations') / 'failed-attempt-001.json'
    failed.write_text('{"error_type":"APITimeoutError"}')
    failure_before = failed.read_bytes()
    results = [runner._run_job(job) for job in jobs]
    assert len(results) == 3360
    assert calls == dispatched == [job.key for job in jobs[3333:]]
    assert all((p.read_bytes(), p.stat().st_mtime_ns) == data for p, data in before.items())
    assert failed.read_bytes() == failure_before
    # A second ordinary resume makes zero additional calls.
    for job in jobs[3333:]:
        runner._run_job(job)
    assert len(calls) == 27
    print('resume: 3333 completed judgments preserved byte-for-byte; exactly 27 missing dispatched; no duplicate calls')


@pytest.mark.parametrize('provider', ['anthropic', 'openai'])
def test_midstream_connection_error_preserves_sdk_classification(monkeypatch, provider):
    requests, streams, clients = _install_network(monkeypatch, provider, '{}')

    def broken(self):
        yield b': keepalive\n\n'
        raise httpx.ReadError('connection lost', request=self.request)

    monkeypatch.setattr(TimedNetworkStream, '__iter__', broken)
    error = anthropic.APIConnectionError if provider == 'anthropic' else openai.APIConnectionError
    with pytest.raises(error):
        if provider == 'anthropic':
            provider_streams.anthropic_response(api_key='fake', timeout=300, model='fixture', max_tokens=10, messages=[])
        else:
            provider_streams.openai_response(api_key='fake', timeout=300, model='fixture')
    assert len(requests) == 1 and streams[0].closed and clients[0].is_closed


@pytest.mark.parametrize('status', ['failed', 'incomplete'])
def test_openai_terminal_failure_is_rejected(monkeypatch, status):
    requests, streams, clients = _install_network(monkeypatch, 'openai', '{}')
    monkeypatch.setattr(TimedNetworkStream, '__iter__', lambda self: iter([
        _sse(dict(type=f'response.{status}', response=dict(status=status)))
    ]))
    with pytest.raises(RuntimeError, match='OpenAI stream failed'):
        provider_streams.openai_response(api_key='fake', timeout=300, model='fixture')
    assert len(requests) == 1 and streams[0].closed and clients[0].is_closed


def test_sparse_criterion_ids_follow_contract_order():
    levels = {'criterion_88': {'C': 3, 'D': -2}, 'criterion_3': {'A': 7, 'B': 0}}
    decoded = indexed_rubric.decode_output(json.dumps(_wire(['1|first', '0|second'])), 2)
    report = rubric_judge.parse_rubric_score_output(decoded, levels)
    assert list(report['criteria']) == ['criterion_88', 'criterion_3']
    assert report['criteria'] == {'criterion_88': {'level': 'D', 'reason': 'first'},
                                  'criterion_3': {'level': 'A', 'reason': 'second'}}


def test_terminal_anthropic_token_truncation_is_not_a_completed_answer(monkeypatch):
    original = _events
    def truncated(provider, text, **kwargs):
        return [(delay, chunk.replace(b'end_turn', b'max_tokens'))
                for delay, chunk in original(provider, text, **kwargs)]
    monkeypatch.setattr(__import__(__name__), '_events', truncated)
    _install_network(monkeypatch, 'anthropic', '{}')
    with pytest.raises(provider_streams.IncompleteProviderResponse, match='max_tokens'):
        provider_streams.anthropic_response(api_key='fake', timeout=300, model='fixture',
                                           max_tokens=10, messages=[])
