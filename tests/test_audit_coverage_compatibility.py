"""Private coverage accepts native producer reuse, never changed scoring settings."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.submission_revision.evaluation import indexed_rubric as wire, jobs, rubric_judge, resume
from rubric_gen.submission_revision.evaluation.rubric_score import _rubric_score_attempt_id
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricGeneration
from test_evaluation_rubric_judge import _many_criterion_rubric
from test_opus_cardinality import _keyed
from test_revision_evaluation import _target
from test_runtime_reliability import _wire, _strings, _text


@pytest.fixture
def checker(monkeypatch):
    directory = Path(__file__).resolve().parents[1] / 'scripts/diagnostics'
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location('coverage_checker_under_test', directory / 'check_audit_coverage.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(rubric_judge, '_generate_response', lambda *a, **k: pytest.fail('provider call'))
    return module


def _panel(tmp_path, contract=wire.V5_STRUCTURED_OUTPUT):
    target = _target(tmp_path)
    (tmp_path / 'instruction.md').write_text('Implement the task.')
    rubric = tmp_path / 'score-rubric.txt'
    rubric.write_text(_many_criterion_rubric(1))
    root = tmp_path / 'audit/rubric_score'
    runner = RubricScoreRunner(jobs.EvaluationConfig(experiment=SimpleNamespace(),
        study_dir=tmp_path / 'study', paraphrase_dir=tmp_path / 'pool',
        output_dir=root, max_concurrency=1, resume=True), (target,))
    native_judge = runner._judge_for_job
    def judge_for(job):
        judge = native_judge(job)
        judge.review_inputs = lambda _: ('evidence', 'answer')
        return judge
    runner._judge_for_job = judge_for
    entries, references, completed = [], [], []
    for model in ('claude-opus-5', 'gpt-5.6-sol'):
        job = jobs.RubricScoreJob(target=target, model=model, artifact='initial',
            rubric_path=rubric, roles=(), generation_bindings=(), grading_identity={},
            review_input_sha256=sha256_text('evidence'), answer_input_sha256=sha256_text('answer'),
            evaluation_implementation_sha256='b' * 64)
        judge = runner._judge_for_job(job)
        job = replace(job, grading_identity={**judge.scoring_identity(), 'scoring_implementation_sha256': 'a' * 64})
        spec = rubric_judge.build_rubric_score_run_spec(rubric_text=rubric.read_text(),
            review_text='evidence', answer_text='answer', requested_model=model, seed=7, indexed_contract=contract)
        render = {wire.V5_STRUCTURED_OUTPUT: _wire, wire.V6_STRUCTURED_OUTPUT: _keyed,
                  wire.V7_STRUCTURED_OUTPUT: _strings, wire.STRUCTURED_OUTPUT: _text}[contract]
        value = render(['0|evidence']) if model.startswith('claude') else {
            'criteria': [{'level_index': 0, 'reason': 'evidence'}], 'overall_reasoning': 'overall'}
        generation = FullRubricGeneration(text=json.dumps(value), provider=spec.provider,
            requested_model=model, effective_model=model, response_id='saved',
            request_parameters=rubric_judge._request_parameters(spec), usage={'output_tokens': 100})
        records = rubric_judge._records_from_generation(spec, generation, rubric_text=rubric.read_text())
        attempt = _rubric_score_attempt_id(job)
        evaluation_root = judge._evaluation_root(job.submission, attempt)
        judge._publish(root=evaluation_root, records=records, scoring_identity=job.grading_identity,
                       review_text='evidence', answer_text='answer')
        record = {**jobs._rubric_score_judgment_identity(job), 'score': records.score,
            'attempt_id': attempt, 'engine_execution': spec.as_json(),
            'evaluation_path': str(evaluation_root / 'evaluation.json'),
            'validation_path': str(evaluation_root / 'score_validation.json')}
        runner.output.write_json(('records', f'{job.key}.json'), record)
        # Native planning keeps the old semantic key but reports the current
        # judge implementation. Actual records and assignment refs remain old.
        entries.append(jobs._rubric_score_plan_entry(job=job, judge=judge,
            review_text='evidence', answer_text='answer', shape={}))
        references.append({**record, 'judgment_key': job.key})
        completed.append(job)
    return root, {'predispatch_plan': {'jobs': entries}, 'planned_semantic_judgment_count': 2,
                  'records': references}, runner, completed


def _snapshot(root):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('contract', [wire.V5_STRUCTURED_OUTPUT, wire.V6_STRUCTURED_OUTPUT,
                                    wire.V7_STRUCTURED_OUTPUT, wire.STRUCTURED_OUTPUT])
def test_mixed_producer_coverage_is_valid_and_byte_identical(tmp_path, checker, contract):
    root, summary, runner, completed = _panel(tmp_path, contract)
    before = _snapshot(root)
    summary_before = deepcopy(summary)
    assert all(r['grading_identity'] != j['grading_identity'] for r, j in
               zip(summary['records'], summary['predispatch_plan']['jobs'], strict=True))
    checker.check_semantic_records(root, 'rubric_score', summary)
    for job in completed:
        path = root / 'records' / f'{job.key}.json'
        resume.validate_saved_rubric(runner, job, json.loads(path.read_text()), path)
    assert _snapshot(root) == before and summary == summary_before


@pytest.mark.parametrize('field,value', [('effective_judge_model', 'gpt-5.6-sol'),
    ('review_mode', 'answer'), ('max_review_chars', 512), ('rendered_rubric_sha256', 'f' * 64),
    ('grading_engine', 'changed'), ('benchmark', 'changed'), ('rubric_id', 'changed')])
def test_semantic_comparison_rejects_substantive_grading_changes(tmp_path, checker, field, value):
    root, summary, _, _ = _panel(tmp_path)
    summary['predispatch_plan']['jobs'][0]['grading_identity'][field] = value
    before = _snapshot(root)
    with pytest.raises(AssertionError, match='grading_identity'):
        checker.check_semantic_records(root, 'rubric_score', summary)
    assert _snapshot(root) == before


def _change_execution(root, summary, field, value):
    """Keep receipts internally consistent so native scientific checks decide."""
    reference = summary['records'][0]
    path = root / 'records' / f"{reference['judgment_key']}.json"
    raw = json.loads(path.read_text())
    directory = Path(raw['evaluation_path']).parent
    data = {name: json.loads((directory / name).read_text()) for name in
            ('evaluation.json', 'metadata.json', 'score_validation.json', 'usage.json')}
    execution = {**raw['engine_execution'], field: value}
    raw['engine_execution'] = reference['engine_execution'] = execution
    data['metadata.json']['engine_execution'] = execution
    data['score_validation.json']['engine_execution'] = execution
    data['evaluation.json']['full_rubric_structured']['execution'] = execution
    data['usage.json']['execution'] = execution
    if field in {'reasoning_effort', 'max_output_tokens_per_call'}:
        parameter = 'max_output_tokens' if field == 'max_output_tokens_per_call' else field
        data['usage.json']['call']['request_parameters'][parameter] = value
    for name in ('evaluation.json', 'score_validation.json', 'usage.json'):
        (directory / name).write_text(json.dumps(data[name]))
    for digest, filename in [('evaluation_sha256', 'evaluation.json'), ('reward_sha256', 'reward.json'),
                             ('score_validation_sha256', 'score_validation.json'), ('usage_sha256', 'usage.json')]:
        data['metadata.json']['artifacts'][digest] = sha256_file(directory / filename)
    (directory / 'metadata.json').write_text(json.dumps(data['metadata.json']))
    path.write_text(json.dumps(raw))


@pytest.mark.parametrize('field,value', [('requested_model', 'gpt-5.6-sol'), ('provider', 'openai'),
    ('reasoning_effort', 'high'), ('max_output_tokens_per_call', 65536),
    ('system_prompt_sha256', 'f' * 64)])
def test_native_closure_validator_rejects_model_effort_budget_and_prompt_changes(tmp_path, checker, field, value):
    root, summary, runner, completed = _panel(tmp_path)
    _change_execution(root, summary, field, value)
    before = _snapshot(root)
    # Reporting's narrow identity comparison complements the existing native
    # closure validator; do not create another execution protocol in diagnostics.
    job = completed[0]
    path = root / 'records' / f'{job.key}.json'
    with pytest.raises(RuntimeError, match='saved rubric (request setting|scientific instructions)'):
        resume.validate_saved_rubric(runner, job, json.loads(path.read_text()), path)
    assert _snapshot(root) == before


@pytest.mark.parametrize('damage', ['missing-record', 'reference-score', 'record-model',
    'validation-provenance', 'validation-score', 'evaluation-score', 'symlink'])
def test_original_evidence_checks_stay_exact(tmp_path, checker, damage):
    root, summary, _, _ = _panel(tmp_path)
    reference = summary['records'][0]
    record = root / 'records' / f"{reference['judgment_key']}.json"
    if damage == 'missing-record': record.unlink()
    elif damage == 'reference-score': reference['score'] -= 1
    elif damage == 'record-model':
        raw = json.loads(record.read_text()); raw['model'] = 'gpt-5.6-sol'; record.write_text(json.dumps(raw))
    elif damage == 'symlink':
        original = record.read_bytes(); record.unlink()
        elsewhere = root / 'outside.json'; elsewhere.write_bytes(original); record.symlink_to(elsewhere)
    else:
        path = Path(reference['validation_path'] if damage.startswith('validation') else reference['evaluation_path'])
        raw = json.loads(path.read_text())
        if damage == 'validation-provenance': raw['scoring_implementation_sha256'] = 'f' * 64
        else: raw['score' if damage == 'validation-score' else 'total_score'] -= 1
        path.write_text(json.dumps(raw))
    with pytest.raises(AssertionError):
        checker.check_semantic_records(root, 'rubric_score', summary)
