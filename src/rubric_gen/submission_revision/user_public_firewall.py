"""Two bounded User-only public-evidence pipelines; no raw private text crosses.

Requests are assembled from an explicit public allowlist. Address validity is
not semantic verification. Per-stage records use the ordinary model generator,
bounded retries, atomic writes and exact request equality for missing-only resume.
"""
from dataclasses import asdict, replace
import json
from pathlib import Path
import time
import jsonschema

from rubric_gen.artifacts.serialization import write_json_atomic
from .evolution_serialization import canonical_json
from .trace_defense_evidence_v2 import PublicDocument, references_schema, bind_references
from . import user_public_firewall_prompts as prompts

VARIANTS = {'attack_defense_user_public_p1': False, 'attack_defense_user_public_p2': True}
ISSUE_TYPES = ('missing_task_requirement', 'recomputation_needed', 'method_validity',
               'unsupported_claim', 'inconsistent_public_outputs', 'scope_or_population_check',
               'evidence_traceability', 'implementation_check',
               'documentation_or_reproducibility', 'other_verification')


def obj(**properties):
    return dict(type='object', additionalProperties=False, required=list(properties), properties=properties)


def enum(*values):
    if not values:
        raise ValueError('empty enum')
    return {'type': 'string', 'enum': list(values)}


def documents(*, instruction, current_artifact, history_context):
    # Caller supplies exactly the ordinary simulator's public history context.
    return {key: PublicDocument(key, text) for key, text in
            (('task', instruction), ('artifact', current_artifact), ('history', history_context))}


def public_payload(docs):
    if set(docs) != {'task', 'artifact', 'history'} or any(k != d.source_id for k, d in docs.items()):
        raise ValueError('public review requires only approved public sources')
    return {'public_sources': [doc.model_record() for doc in docs.values()]}


def locator_request(docs, full_feedback_text, *, max_concerns, max_output_tokens):
    from .user_simulator import SimulatedUserRequest
    refs = references_schema(docs); refs['minItems'] = 1
    schema = obj(decision=enum('candidate_issue', 'no_issue'), issues={
        'type': 'array', 'maxItems': max_concerns,
        'items': obj(issue_type=enum(*ISSUE_TYPES), public_refs=refs,
                     priority={'type': 'integer', 'minimum': 1, 'maximum': 3})})
    evidence = {**public_payload(docs), 'private_evaluator_feedback': full_feedback_text}
    return SimulatedUserRequest(prompts.LOCATOR, canonical_json(evidence), schema, max_output_tokens,
                                schema_name='user_firewall_locator')


def public_issue(issue, docs):
    # Deliberate allowlist: no private source IDs, priority or arbitrary text.
    if issue['issue_type'] not in ISSUE_TYPES:
        raise ValueError('unknown public issue type')
    bind_references(issue['public_refs'], docs)
    if not issue['public_refs']:
        raise ValueError('public issue needs evidence')
    return {'issue_type': issue['issue_type'], 'public_refs': issue['public_refs']}


def review_request(docs, issue, *, stage, max_output_tokens, verification=None):
    from .user_simulator import SimulatedUserRequest, CONCERN_CATEGORIES
    evidence = {**public_payload(docs), 'candidate': public_issue(issue, docs)}
    refs = references_schema(docs)
    if stage == 'verify':
        schema = obj(decision=enum('supported_defect', 'unresolved_verification', 'unsupported'),
                     public_refs=refs, rationale={'type': 'string', 'minLength': 1, 'maxLength': 1000})
        instructions = prompts.VERIFIER
    elif stage == 'render':
        concern = obj(category=enum(*CONCERN_CATEGORIES), feedback={'type': 'string', 'minLength': 1, 'maxLength': 600})
        schema = obj(decision=enum('observed_defect', 'verification_request', 'no_issue'),
                     public_refs=refs, concern={'anyOf': [concern, {'type': 'null'}]})
        instructions = prompts.PUBLIC_REVIEW
        if verification is not None:
            # validate_against is called by orchestration before this request.
            if verification['decision'] == 'unsupported':
                raise ValueError('unsupported candidate must not be rendered')
            evidence['public_verification'] = {k: verification[k] for k in ('decision', 'public_refs', 'rationale')}
            instructions += '\n\n' + prompts.VERIFIED_RENDERING
    else:
        raise ValueError('unknown public review stage')
    return SimulatedUserRequest(instructions, canonical_json(evidence), schema, max_output_tokens,
                                schema_name='user_firewall_' + stage)


def validate_against(value, request, docs, *, verification=None):
    errors = list(jsonschema.Draft202012Validator(request.schema).iter_errors(value))
    if errors:
        raise ValueError('; '.join(f'{list(e.path)}: {e.message}' for e in errors)[:1200])
    if request.schema_name == 'user_firewall_locator':
        if (value['decision'] == 'no_issue') != (not value['issues']):
            raise ValueError('locator decision/issues disagree')
        bindings = []
        for index, issue in enumerate(value['issues'], 1):
            if issue['priority'] != index:
                raise ValueError('locator priorities must follow list order starting at 1')
            bindings.append(bind_references(issue['public_refs'], docs))
        return bindings
    bindings = bind_references(value['public_refs'], docs)
    if request.schema_name == 'user_firewall_verify':
        if value['decision'] != 'unsupported' and not bindings:
            raise ValueError('verification needs public evidence')
    else:
        if (value['decision'] == 'no_issue') != (value['concern'] is None):
            raise ValueError('renderer decision/concern disagree')
        if value['decision'] != 'no_issue' and not bindings:
            raise ValueError('rendered concern needs public evidence')
        if verification and verification['decision'] == 'unresolved_verification' and value['decision'] == 'observed_defect':
            raise ValueError('unresolved verification cannot become an established defect')
    return bindings


def pipeline(version, docs, full_feedback_text, *, max_concerns, max_output_tokens, call):
    """Same deterministic flow for execution and provider-free replay."""
    verified = VARIANTS[version]
    request = locator_request(docs, full_feedback_text, max_concerns=max_concerns, max_output_tokens=max_output_tokens)
    located = call('locator', request, None)
    validate_against(located, request, docs)
    concerns = []
    for index, issue in enumerate(located['issues'], 1):
        verification = None
        if verified:
            request = review_request(docs, issue, stage='verify', max_output_tokens=max_output_tokens)
            verification = call(f'issue-{index}-verify', request, None)
            validate_against(verification, request, docs)
            if verification['decision'] == 'unsupported':
                continue
        request = review_request(docs, issue, stage='render', max_output_tokens=max_output_tokens, verification=verification)
        rendered = call(f'issue-{index}-render', request, verification)
        validate_against(rendered, request, docs, verification=verification)
        if rendered['concern'] is not None:
            concerns.append(rendered['concern'])
    from .user_simulator import _validate_feedback_output
    return _validate_feedback_output({'decision': 'revise' if concerns else 'accept', 'concerns': concerns}, max_concerns=max_concerns)


def execute(simulator, *, version, docs, full_feedback_text, directory):
    """Save each paid stage immediately; a restart never buys a completed stage."""
    from .user_simulator import _validate_request_size, load_json_strict
    records = []

    def call(name, request, verification):
        path = Path(directory) / name / 'result.json'
        identity = {'version': version, 'stage': name, 'request': asdict(request), 'simulator': simulator.identity()}
        _validate_request_size(request, simulator.config.max_request_bytes)
        if path.exists():
            record = json.loads(path.read_text())
            if record['identity'] != identity:
                raise RuntimeError('firewall stage request changed on resume')
        else:
            attempts = []
            # Attempt records survive interruption even before result.json.
            for attempt in range(1, simulator.config.max_retries + 2):
                prior_path = path.parent / f'attempt-{attempt}.json'
                if prior_path.exists():
                    old = json.loads(prior_path.read_text())
                    if old['identity'] != identity:
                        raise RuntimeError('firewall attempt request changed on resume')
                    attempts.append(old)
                    if old['status'] == 'valid_result':
                        break
                    continue
                actual_request = request
                if attempts and attempts[-1]['status'] == 'invalid_response':
                    prior = attempts[-1]
                    actual_request = replace(request, instructions=request.instructions +
                        '\n\nRepair only the output contract of the previous response. Keep valid scientific decisions and concern/rationale text unchanged. '
                        + 'Do not seek a preferred assessment. Validation error: ' + prior['error'],
                        evidence=request.evidence + '\n\nPrevious response:\n' + prior.get('raw_text', ''))
                start = time.monotonic(); generated = None
                attempt_record = {'identity': identity, 'attempt': attempt, 'request': asdict(actual_request)}
                try:
                    _validate_request_size(actual_request, simulator.config.max_request_bytes)
                    generated = simulator._generator(simulator.config, actual_request)
                    value = load_json_strict(generated.text)
                    bindings = validate_against(value, request, docs, verification=verification)
                    # Locator repairs may fix addresses/encoding but no model-generated
                    # scientific prose travels out of that stage. Preserve valid public
                    # judgments during address-only repairs.
                    if attempts and attempts[-1].get('parsed') and request.schema_name != 'user_firewall_locator':
                        old = attempts[-1]['parsed']
                        for key in ('decision', 'concern', 'rationale'):
                            if key in old and key in value and not list(jsonschema.Draft202012Validator(request.schema['properties'][key]).iter_errors(old[key])):
                                if old[key] != value[key]:
                                    raise ValueError('contract repair changed a valid scientific field: ' + key)
                    simulator._validate_generation_provenance(generated.provenance())
                    attempt_record.update(status='valid_result', output=value, source_bindings=bindings,
                                          provider=generated.provenance(), raw_text=generated.text)
                except Exception as exc:
                    attempt_record.update(status='invalid_response' if isinstance(exc, ValueError) else 'provider_failure',
                                          error=f'{type(exc).__name__}: {exc}')
                    if generated is not None:
                        attempt_record.update(raw_text=generated.text, provider=generated.provenance())
                        try:
                            attempt_record['parsed'] = load_json_strict(generated.text)
                        except ValueError:
                            pass
                attempt_record['wall_seconds'] = time.monotonic() - start
                write_json_atomic(prior_path, attempt_record)
                attempts.append(attempt_record)
                if attempt_record['status'] == 'valid_result':
                    break
            final = attempts[-1]
            record = {'identity': identity, 'attempts': attempts, 'status': final['status']}
            if final['status'] == 'valid_result':
                record.update(output=final['output'], source_bindings=final['source_bindings'])
            write_json_atomic(path, record)
        if record['status'] != 'valid_result':
            raise RuntimeError(f'firewall stage {name} exhausted bounded attempts: {record["attempts"][-1].get("error")}')
        if validate_against(record['output'], request, docs, verification=verification) != record['source_bindings']:
            raise RuntimeError('firewall source bindings changed')
        for attempt in record['attempts']:
            if 'provider' in attempt:
                simulator._validate_generation_provenance(attempt['provider'])
        records.append(record)
        return record['output']

    output = pipeline(version, docs, full_feedback_text, max_concerns=simulator.config.max_concerns,
                      max_output_tokens=simulator.config.max_output_tokens, call=call)
    return {'version': version, 'stages': records, 'output': output}


def replay(simulator, record, *, version, docs, full_feedback_text):
    stages = iter(record['stages'])
    def call(name, request, verification):
        stage = next(stages)
        expected = {'version': version, 'stage': name, 'request': asdict(request), 'simulator': simulator.identity()}
        if stage['identity'] != expected or stage['status'] != 'valid_result':
            raise ValueError('firewall replay request/stage differs')
        if validate_against(stage['output'], request, docs, verification=verification) != stage['source_bindings']:
            raise ValueError('firewall replay source bindings differ')
        attempts = stage['attempts']
        if not 1 <= len(attempts) <= simulator.config.max_retries + 1:
            raise ValueError('firewall attempt allowance exceeded')
        if attempts[-1]['output'] != stage['output'] or attempts[-1]['status'] != 'valid_result':
            raise ValueError('firewall terminal response changed')
        for attempt in attempts:
            if 'provider' in attempt:
                simulator._validate_generation_provenance(attempt['provider'])
        return stage['output']
    output = pipeline(version, docs, full_feedback_text, max_concerns=simulator.config.max_concerns,
                      max_output_tokens=simulator.config.max_output_tokens, call=call)
    if next(stages, None) is not None or record['version'] != version or output != record['output']:
        raise ValueError('firewall replay stages/output differ')
    return output
