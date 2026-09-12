"""Reuse complete audited stages by scientific inputs, retaining producer provenance.

Runtime source digests remain in the original records. They do not require buying
an already completed judgment after scheduling or transport code changes. Every
reused response is checked against the current inputs and replayed locally.
"""
from __future__ import annotations

import json
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.evaluation import jobs
from rubric_gen.submission_revision.judge import JUDGE_MAX_ATTEMPTS


def scientific_identity(identity):
    value = dict(identity)
    value.pop('evaluation_implementation_sha256', None)
    for field in ('grading_identity', 'implementation_identity'):
        if field in value:
            value[field] = {k: v for k, v in value[field].items() if k != 'scoring_implementation_sha256'}
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _completed_summary(output, config):
    path = output.path('summary.json')
    if not config.resume or not path.exists():
        return None
    summary = read_json_object(path, 'saved stage summary')
    if summary.get('status') != 'completed':
        return None
    if (summary.get('experiment_id') != config.experiment.experiment_id
            or summary.get('study_dir') != str(config.study_dir.resolve())
            or summary.get('models') != list(config.experiment.outcome_audit['models'])):
        raise RuntimeError('completed stage belongs to another study or panel')
    return summary


def reuse_completed_rubric(runner) -> bool:
    summary = _completed_summary(runner.output, runner.config)
    if summary is None:
        return False
    prepared = runner._prepared
    expected = {scientific_identity(jobs._rubric_score_judgment_identity(job)): job
                for job in prepared.unique_jobs}
    identities = set()
    original_identities = {}
    original_records = {}
    saved_keys = set()
    identity_fields = set(jobs._rubric_score_judgment_identity(prepared.unique_jobs[0]))
    for path in sorted(runner.output.path('records').glob('*.json')):
        record = read_json_object(path, 'saved rubric judgment')
        identity = {k: record[k] for k in identity_fields}
        semantic = scientific_identity(identity)
        if semantic not in expected or semantic in identities or jobs._semantic_judgment_key(identity) != path.stem:
            raise RuntimeError(f'saved rubric judgment differs from the required semantic work: {path}')
        job = expected[semantic]
        validate_saved_rubric(runner, job, record, path)
        identities.add(semantic)
        original_identities[semantic] = identity
        original_records[semantic] = record
        saved_keys.add(path.stem)
    if (identities != set(expected) or summary.get('successful_semantic_judgment_count') != len(expected)
            or {r['judgment_key'] for r in summary['records']} != saved_keys):
        raise RuntimeError('completed rubric summary has missing or duplicate required work')
    from dataclasses import replace
    from .rubric_score import _rubric_score_assignment_reference_sha256
    original_jobs = tuple(replace(job,
        grading_identity=original_identities[scientific_identity(jobs._rubric_score_judgment_identity(job))]['grading_identity'],
        evaluation_implementation_sha256=original_identities[scientific_identity(jobs._rubric_score_judgment_identity(job))]['evaluation_implementation_sha256'])
        for job in prepared.jobs)
    if _rubric_score_assignment_reference_sha256(original_jobs) != summary['assignment_reference_identity_sha256']:
        raise RuntimeError('completed rubric selected/heldout or generation bindings changed')
    from .rubric_score import _rubric_score_job_identity
    from .runner import _summarize_rubric_scores
    references = []
    for job in original_jobs:
        record = original_records[scientific_identity(jobs._rubric_score_judgment_identity(job))]
        references.append({**_rubric_score_job_identity(job), 'judgment_key': job.key,
                           **{k: record[k] for k in ('score','attempt_id','validation_path','evaluation_path')}})
    references.sort(key=jobs._record_sort_key)
    if references != summary['records']:
        summary['records'] = references
        summary['assignments'] = _summarize_rubric_scores(prepared.targets, references, tuple(summary['models']))
        runner.output.write_json(('summary.json',), summary)
    print(f"Reused {len(identities)} completed rubric judgments; producer records unchanged", flush=True)
    return True


def reuse_completed_free(runner) -> bool:
    from rubric_gen.submission_revision.evaluation.score_execution import _validate_record
    from rubric_gen.submission_revision.evaluation import absolute_score, pairwise_preference
    prepared = runner._prepared
    parts = (
        (runner.absolute_output, prepared.unique_absolute_jobs, jobs._absolute_judgment_identity,
         jobs._rubric_free_absolute_score_request, absolute_score.validate_verdict),
        (runner.pairwise_output, prepared.unique_pairwise_jobs, jobs._pairwise_judgment_identity,
         jobs._pairwise_preference_request, pairwise_preference.validate_verdict),
    )
    summaries = [_completed_summary(output, runner.config) for output, *_ in parts]
    if any(summary is None for summary in summaries):
        return False
    count = 0
    for (output, planned, identity_for, request_for, validator), summary in zip(parts, summaries, strict=True):
        expected = {scientific_identity(identity_for(job, request_for(job))): job for job in planned}
        seen, keys = set(), set()
        original_records = {}
        for path in sorted(output.path('records').glob('*.json')):
            record = read_json_object(path, 'saved rubric-free record')
            fields = set(identity_for(planned[0], request_for(planned[0]))) if planned else set()
            identity = {key: record[key] for key in fields}
            semantic = scientific_identity(identity)
            if semantic not in expected or semantic in seen or jobs._semantic_judgment_key(identity) != path.stem:
                raise RuntimeError(f'saved free-score work differs: {path}')
            _validate_record(record=record, identity=identity, validator=validator,
                             model=expected[semantic].model, max_attempts=JUDGE_MAX_ATTEMPTS)
            if summary['completed_record_sha256s'][path.stem] != sha256_file(path):
                raise RuntimeError(f'saved free-score record changed: {path}')
            seen.add(semantic); keys.add(path.stem)
            original_records[semantic] = record
        if seen != set(expected) or {r['judgment_key'] for r in summary['records']} != keys:
            raise RuntimeError('completed free-score summary has missing work')
        from dataclasses import replace
        reference = absolute_score.assignment_reference if output is runner.absolute_output else pairwise_preference.assignment_reference
        references = prepared.absolute_jobs if output is runner.absolute_output else prepared.pairwise_jobs
        expected_references = []
        for job in references:
            semantic = scientific_identity(identity_for(job, request_for(job)))
            record = original_records[semantic]
            original_job = replace(job, implementation_identity=record['implementation_identity'])
            expected_references.append(reference(original_job, record))
        canonical = lambda values: sorted(json.dumps(v, sort_keys=True) for v in values)
        bindings = lambda values: [{k:v for k,v in r.items() if k != 'verdict'} for r in values]
        if canonical(bindings(expected_references)) != canonical(bindings(summary['records'])):
            raise RuntimeError('completed free-score assignment/artifact/order bindings changed')
        if canonical(expected_references) != canonical(summary['records']):
            expected_references.sort(key=jobs._record_sort_key)
            summary['records'] = expected_references
            summary['assignments'] = (absolute_score.summarize(prepared.targets, expected_references, prepared.models)
                if output is runner.absolute_output else pairwise_preference.summarize(
                    prepared.targets, expected_references, prepared.models, prepared.pairwise_order_plan))
            output.write_json(('summary.json',), summary)
        count += len(seen)
    print(f"Reused {count} completed absolute/pairwise judgments; producer records unchanged", flush=True)
    return True


def validate_saved_rubric(runner, job, record, path):
    identity = {k: record[k] for k in jobs._rubric_score_judgment_identity(job)}
    judge = runner._judge_for_job(job)
    evaluation_path = runner.output.contained_regular_file(Path(record['evaluation_path']))
    validation_path = runner.output.contained_regular_file(Path(record['validation_path']))
    root = evaluation_path.parent
    metadata = read_json_object(root / 'metadata.json', 'saved rubric metadata')
    if (metadata['scoring_identity'] != identity['grading_identity']
            or metadata['review_input_sha256'] != job.review_input_sha256
            or metadata['answer_input_sha256'] != job.answer_input_sha256):
        raise RuntimeError('saved rubric response input provenance differs')
    for name, filename in [('evaluation_sha256','evaluation.json'), ('reward_sha256','reward.json'),
                           ('score_validation_sha256','score_validation.json'), ('usage_sha256','usage.json')]:
        artifact = runner.output.contained_regular_file(root / filename)
        if metadata['artifacts'][name] != sha256_file(artifact):
            raise RuntimeError(f'saved rubric artifact changed: {artifact}')
    evaluation = read_json_object(evaluation_path, 'saved rubric evaluation')
    validation = read_json_object(validation_path, 'saved rubric validation')
    if any(validation.get(k) != v for k, v in identity['grading_identity'].items()):
        raise RuntimeError('saved rubric grading provenance differs')
    from rubric_gen.submission_revision.evaluation.rubric_judge import build_rubric_score_run_spec
    from rubric_gen.submission_revision.judging.full_rubric_protocol import records_from_report
    review, answer = judge.review_inputs(job.submission)
    execution = metadata['engine_execution']
    spec = build_rubric_score_run_spec(rubric_text=judge.rubric.text, review_text=review,
                                     answer_text=answer, requested_model=job.model, seed=execution['engine_seed'])
    # Preserve actual recorded transport/representation. All scientific
    # settings, including effort and output budgets, must still match.
    current = spec.as_json()
    for field in ('requested_model', 'provider', 'engine_seed', 'temperature', 'provider_seed',
                  'reasoning_effort', 'max_output_tokens_per_call'):
        if execution.get(field) != current.get(field):
            raise RuntimeError(f'saved rubric request setting differs: {field}')
    from rubric_gen.submission_revision.evaluation.rubric_judge import RUBRIC_SCORE_SYSTEM_PROMPT, _system_prompt
    from rubric_gen.submission_revision.evaluation import indexed_rubric
    from rubric_gen.artifacts.hashing import sha256_text
    prompt_hashes = {current['system_prompt_sha256'], sha256_text(RUBRIC_SCORE_SYSTEM_PROMPT)}
    if spec.provider == 'anthropic' and execution.get('structured_output_contract') in {
            indexed_rubric.V5_STRUCTURED_OUTPUT, indexed_rubric.V6_STRUCTURED_OUTPUT,
            indexed_rubric.V7_STRUCTURED_OUTPUT, indexed_rubric.STRUCTURED_OUTPUT}:
        # Reconstruct only the recorded format paragraph with the unchanged
        # scientific instructions; no arbitrary producer-source whitelist.
        prompt_hashes = {sha256_text(_system_prompt('anthropic', execution['structured_output_contract']))}
    if execution.get('system_prompt_sha256') not in prompt_hashes:
        raise RuntimeError('saved rubric scientific instructions differ')
    replay = records_from_report(rubric_text=judge.rubric.text,
                                 raw_report=evaluation['full_rubric_structured']['raw_report'], spec=spec,
                                 call_usage=read_json_object(root / 'usage.json', 'saved rubric usage')['call'])
    if (replay.score != record['score'] or replay.score != validation['score']
            or replay.evaluation['criteria'] != evaluation['criteria']
            or replay.score != evaluation['total_score']):
        raise RuntimeError('saved rubric response does not reproduce its score')


def _incomplete_output(output, resume):
    if not resume or not output.path('manifest.json').exists():
        return False
    summary = output.path('summary.json')
    return not summary.exists() or read_json_object(summary, 'stage summary').get('status') != 'completed'


def adopt_saved_rubric_jobs(runner, planned):
    """Bind known results to their original keys; new work keeps current provenance."""
    if not _incomplete_output(runner.output, runner.config.resume):
        return planned
    from dataclasses import replace
    expected = {scientific_identity(jobs._rubric_score_judgment_identity(j)): j for j in planned}
    reused = {}
    runner._reused_records = {}
    for path in sorted(runner.output.path('records').glob('*.json')):
        record = read_json_object(path, 'saved rubric judgment')
        fields = jobs._rubric_score_judgment_identity(planned[0])
        identity = {k: record[k] for k in fields}
        semantic = scientific_identity(identity)
        if semantic not in expected or semantic in reused or jobs._semantic_judgment_key(identity) != path.stem:
            raise RuntimeError('saved rubric record does not identify unique required work')
        validate_saved_rubric(runner, expected[semantic], record, path)
        reused[semantic] = identity
        runner._reused_records[path.stem] = record
    adopted = tuple(replace(job, grading_identity=reused[semantic]['grading_identity'],
                         evaluation_implementation_sha256=reused[semantic]['evaluation_implementation_sha256'])
                 if (semantic := scientific_identity(jobs._rubric_score_judgment_identity(job))) in reused else job
                 for job in planned)
    _prepare_saved_v5_replays(runner, adopted)
    return adopted


def _prepare_saved_v5_replays(runner, planned):
    """Identify complete saved responses without publication or provider work."""
    from dataclasses import replace
    from .rubric_judge import SavedV5Response, FullRubricJudgeError
    from .rubric_score import _rubric_score_attempt_id

    runner._saved_v5_replays = {}
    prior = read_json_object(runner.output.path('manifest.json'), 'saved rubric manifest')
    fields = ('model', 'task_instruction_sha256', 'submission_content_sha256',
              'rubric_sha256', 'review_input_sha256', 'answer_input_sha256')
    binding = lambda entry: tuple(entry[field] for field in fields)
    entries = {binding(entry): entry for entry in prior['predispatch_plan']['jobs']}
    unique = {job.key: job for job in planned if job.key not in runner._reused_records
              and job.model.startswith('claude')}
    for job in unique.values():
        identity = jobs._rubric_score_judgment_identity(job)
        entry = entries.get(binding(identity))
        if entry is None:
            continue  # The ordinary stage-plan comparison diagnoses scope changes.
        original = replace(job, grading_identity=entry['grading_identity'],
                           evaluation_implementation_sha256=prior['implementation_identity']['evaluation_sha256'])
        if (original.key != entry['semantic_key'] or scientific_identity(identity) !=
                scientific_identity(jobs._rubric_score_judgment_identity(original))):
            raise RuntimeError('saved rubric response plan provenance differs')
        judge = runner._judge_for_job(original)
        attempt_id = _rubric_score_attempt_id(original)
        root = judge._evaluation_root(original.submission, attempt_id)
        attempts = root.parent / f'{attempt_id}.attempts'
        expected = {'scoring_identity': original.grading_identity,
                    'review_input_sha256': original.review_input_sha256,
                    'answer_input_sha256': original.answer_input_sha256}
        for attempt in range(1, JUDGE_MAX_ATTEMPTS + 1):
            raw = attempts / f'attempt-{attempt:03d}.response.json'
            if not raw.exists():
                continue
            state = runner.output.contained_regular_file(attempts / f'attempt-{attempt:03d}.json')
            candidate = SavedV5Response(state, runner.output.contained_regular_file(raw), expected)
            try:
                candidate.replay(judge, original.submission)
            except FullRubricJudgeError:
                continue  # Incomplete/conflicting content still needs a new judgment.
            runner._saved_v5_replays[job.key] = candidate
            break


def adopt_saved_free_jobs(runner, planned, output, identity_for, request_for, validator):
    if not runner.config.resume or not output.path('manifest.json').exists():
        return planned
    from dataclasses import replace
    from .score_execution import _validate_record
    expected = {scientific_identity(identity_for(j, request_for(j))): j for j in planned}
    reused = {}
    for path in sorted(output.path('records').glob('*.json')):
        record = read_json_object(path, 'saved free-score judgment')
        if not planned:
            raise RuntimeError('unexpected saved free-score work')
        identity = {k: record[k] for k in identity_for(planned[0], request_for(planned[0]))}
        semantic = scientific_identity(identity)
        if semantic not in expected or semantic in reused or jobs._semantic_judgment_key(identity) != path.stem:
            raise RuntimeError('saved free-score record does not identify unique required work')
        _validate_record(record=record, identity=identity, validator=validator,
                         model=expected[semantic].model, max_attempts=JUDGE_MAX_ATTEMPTS)
        reused[semantic] = identity
    return tuple(replace(job, implementation_identity=reused[semantic]['implementation_identity'])
                 if (semantic := scientific_identity(identity_for(job, request_for(job)))) in reused else job
                 for job in planned)


def _plan_science(entry):
    value = dict(entry)
    value.pop('semantic_key', None)
    if 'grading_identity' in value:
        value['grading_identity'] = {k:v for k,v in value['grading_identity'].items() if k != 'scoring_implementation_sha256'}
    if 'shape' in value:
        # Indexed Anthropic formatting changes schema bytes, not evidence,
        # criterion coverage, calls, or the configured output budget.
        value['shape'] = {k:v for k,v in value['shape'].items() if k not in {
            'schema_bytes','payload_bytes','request_content_bytes_per_call','total_request_content_bytes'}}
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def prepare_stage_output(output, manifest, resume, planned=()):
    """Validate a saved stage's scientific plan, retaining its original manifest."""
    path = output.path('manifest.json')
    if not resume or not path.exists():
        output.prepare(manifest, resume)
        return
    prior = read_json_object(path, 'stage manifest')
    if prior == manifest:
        output.prepare(manifest, resume)
        return
    derived = {'implementation_identity', 'predispatch_plan', 'assignment_reference_identity_sha256'}
    if {k:v for k,v in prior.items() if k not in derived} != {k:v for k,v in manifest.items() if k not in derived}:
        raise RuntimeError('evaluation resume scientific scope changed; existing output preserved')
    old_plan, new_plan = prior['predispatch_plan'], manifest['predispatch_plan']
    if sorted(map(_plan_science, old_plan['jobs'])) != sorted(map(_plan_science, new_plan['jobs'])):
        raise RuntimeError('evaluation resume scientific requests changed; existing output preserved')
    if planned:
        from dataclasses import replace
        from .rubric_score import _rubric_score_assignment_reference_sha256
        # Reconstruct the original reference digest from the recorded producer
        # fields solely to validate roles/bindings; never dispatch these views.
        old_by_science = {_plan_science(entry): entry for entry in old_plan['jobs']}
        new_by_key = {entry['semantic_key']: entry for entry in new_plan['jobs']}
        original = tuple(replace(job,
            grading_identity=old_by_science[_plan_science(new_by_key[job.key])]['grading_identity'],
            evaluation_implementation_sha256=prior['implementation_identity']['evaluation_sha256']) for job in planned)
        if _rubric_score_assignment_reference_sha256(original) != prior['assignment_reference_identity_sha256']:
            raise RuntimeError('evaluation resume selected/heldout or generation bindings changed')
    output.prepare(prior, resume=True)
