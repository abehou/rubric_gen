"""Versioned bounded contract repair and exact, revalidated v2 request receipts."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import threading
import time
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from .evolution_serialization import canonical_json, canonical_sha256, load_json_object
from .evolution_provider import RubricProposerProviderError, RubricProposerInputLimitError, StructuredProviderOutput
from .evolution_stage import PROVIDER_FAILURE_MAX_RETRIES, maximum_stage_attempts
from .trace_defense_evidence_v2 import EvidenceContractError
from .trace_defense_v2_schema import ResponseContract
from . import trace_defense_v2_prompts as prompts

STAGE_CONTRACT_VERSION = 'trace-defense-v2-stage-1'


def contract_source_hashes():
    root = Path(__file__).parent
    return {name: sha256_file(root/name) for name in (
        'trace_defense_evidence_v2.py', 'trace_defense_v2_schema.py', 'trace_defense_v2_stage.py',
        'trace_defense_v2_prompts.py', 'trace_defense.py', 'trace_defense_schema.py')}


class TraceStagesV2:
    def __init__(self, proposer, root: Path, *, read_only=False):
        self.proposer, self.root, self.read_only = proposer, root, read_only
        self.version = proposer.red_team_trace_version
        from .trace_defense_registry import recipe
        if recipe(self.version).family != 'v2':
            raise ValueError('v2 stages require an explicit v2 recipe')
        self.records, self.lock, self.key_locks = [], threading.Lock(), {}

    def request(self, stage, evidence, validator):
        if validator.stage != stage:
            raise ValueError('response validator stage differs from request')
        return {'red_team_trace_version': self.version, 'stage': stage,
                'prompt_version': prompts.PROMPT_VERSION, 'prompt': prompts.STAGES[stage],
                'prompt_sha256': prompts.prompt_hashes()[stage],
                'locator_repair_prompt': prompts.LOCATOR_REPAIR_V2,
                'locator_repair_prompt_sha256': prompts.prompt_hashes()['locator_repair'],
                'stage_contract_version': STAGE_CONTRACT_VERSION,
                'validation_source_sha256s': contract_source_hashes(),
                'evidence': canonical_json(evidence), 'schema': validator.schema,
                'response_contract': validator.identity(), 'provider': self.proposer.proposer_contract.record(),
                'max_retries': self.proposer.max_retries, 'locator_repairs_maximum': 2,
                'maximum_stage_attempts': maximum_stage_attempts(self.proposer.max_retries),
                'provider_failure_max_retries': PROVIDER_FAILURE_MAX_RETRIES}

    def call(self, stage, evidence, validator: ResponseContract):
        request = self.request(stage, evidence, validator)
        key = canonical_sha256(request)
        with self.lock:
            key_lock = self.key_locks.setdefault(key, threading.Lock())
        with key_lock:
            record = self._execute(stage, request, key, validator)
        with self.lock:
            self.records.append(record)
        return record['outcome']['value']

    def _execute(self, stage, request, key, validator):
        directory, actual = self.root/key, 0
        path = directory/'result.json'
        provider = self.proposer.proposer_contract
        cache_hit = path.is_file()
        if cache_hit:
            result = load_json_object(path.read_text(), 'v2 request receipt')
            if result['request'] != request or canonical_sha256(result['outcome']) != result['outcome_sha256']:
                raise RuntimeError('v2 request receipt integrity mismatch')
            self._revalidate(result['outcome'], validator)
        else:
            if self.read_only:
                raise RuntimeError('completed v2 generation lacks its exact request receipt')
            directory.mkdir(parents=True, exist_ok=True)
            attempts = [load_json_object(p.read_text(), 'v2 attempt') for p in sorted(directory.glob('attempt-*.json'))]
            if any(a.get('request_sha256') != key or a.get('attempt') != i+1 for i, a in enumerate(attempts)):
                raise RuntimeError('v2 attempt identity/sequence mismatch')
            outcome = None
            state = None
            for index, attempt in enumerate(attempts):
                if attempt.get('permanent'):
                    raise RubricProposerProviderError(f'{stage}: retained permanent failure at {directory}')
                if attempt['status'] == 'valid_result':
                    if index != len(attempts)-1:
                        raise RuntimeError('v2 attempts continued after scientific success')
                    output = StructuredProviderOutput(**attempt['output'])
                    provider.validate_output(output)
                    value = load_json_object(output.response_text, stage)
                    bindings = validator.validate(value)
                    if bindings != attempt['resolved_evidence']:
                        raise RuntimeError('v2 successful attempt source binding changed')
                    outcome = self._valid(value, bindings)
                    cache_hit = True
                state = attempt.get('repair_state', state)
            failures = sum(a['status'] == 'provider_failure' for a in attempts)
            invalid = sum(a['status'] == 'contract_invalid' for a in attempts)
            locator_calls = sum(a['request_kind'] == 'locator_repair' for a in attempts)
            last_errors = attempts[-1].get('validation_errors', []) if attempts else []
            while outcome is None:
                if failures > PROVIDER_FAILURE_MAX_RETRIES:
                    raise RubricProposerProviderError(f'{stage}: provider allowance exhausted at {directory}')
                if (len(attempts) >= request['maximum_stage_attempts'] or invalid >= self.proposer.max_retries+1
                        or (state is not None and locator_calls >= 2)):
                    # Transport exhaustion remains an infrastructure failure, never a scientific empty result.
                    if attempts and attempts[-1]['status'] == 'provider_failure':
                        raise RubricProposerProviderError(f'{stage}: attempt allowance exhausted by transport at {directory}')
                    outcome = {'status': 'contract_exhausted', 'value': None, 'resolved_evidence': {},
                               'source_binding_status': 'not_valid', 'validation_errors': last_errors}
                    break
                kind = 'locator_repair' if state is not None else 'schema_repair' if invalid else 'initial'
                instructions = prompts.LOCATOR_REPAIR_V2 if state is not None else prompts.STAGES[stage]
                if state is not None:
                    payload = {'original_public_inputs': load_json_object(request['evidence'], 'request evidence'),
                               'previous_response': state['previous_response'], 'validation_errors': last_errors,
                               'allowed_edit_fields': state['allowed_edit_fields'], 'locked_fields': state['locked_fields']}
                    attempt_evidence = canonical_json(payload)
                else:
                    attempt_evidence = request['evidence']
                    if invalid:
                        attempt_evidence += '\n\n<repair>\nThe prior response failed the output contract.\n'+canonical_json(last_errors)+'\nReturn a complete corrected response under the supplied schema.\n</repair>'
                attempt = {'request_sha256': key, 'stage': stage, 'attempt': len(attempts)+1,
                           'request_kind': kind, 'instructions_sha256': sha256_text(instructions),
                           'evidence_sha256': sha256_text(attempt_evidence), 'attempt_evidence': attempt_evidence}
                start = time.monotonic()
                actual += 1
                if kind == 'locator_repair':
                    locator_calls += 1
                try:
                    operation = self.proposer.run_proposer
                    if getattr(operation, '__func__', None) is self.proposer._run_direct_proposer.__func__:
                        output = provider.generate(instructions=instructions, evidence=attempt_evidence,
                            response_schema=validator.schema, request_context=self.version, schema_name='trace_defense_v2_'+stage)
                    else:
                        output = operation(stage=stage, evidence=attempt_evidence, response_schema=validator.schema)
                except RubricProposerInputLimitError:
                    raise
                except Exception as exc:
                    failures += 1
                    permanent = (getattr(exc, 'status_code', None) in {400, 401, 403, 404, 422}
                                 or getattr(exc, 'code', None) in {'insufficient_quota', 'invalid_api_key'})
                    attempt.update(status='provider_failure', error=str(exc), error_type=type(exc).__name__, permanent=permanent,
                                   repair_state=state, wall_seconds=time.monotonic()-start)
                    write_json_atomic(directory/f"attempt-{attempt['attempt']:03d}.json", attempt)
                    attempts.append(attempt)
                    if permanent or failures > PROVIDER_FAILURE_MAX_RETRIES:
                        raise RubricProposerProviderError(f'{stage}: provider failure at {directory}') from exc
                    time.sleep(min(.5*2**(failures-1), 8))
                    continue
                value = None
                attempt['output'] = asdict(output)
                try:
                    provider.validate_output(output)
                    value = load_json_object(output.response_text, stage)
                    if state is not None:
                        changed = [k for k, v in state['locked_fields'].items() if value.get(k) != v]
                        if changed:
                            raise EvidenceContractError([{'field': k, 'reason': 'locked_field_changed'} for k in changed])
                    bindings = validator.validate(value)
                except (ValueError, RuntimeError) as exc:
                    invalid += 1
                    last_errors = exc.errors if isinstance(exc, EvidenceContractError) else [{'field': '$', 'reason': str(exc)}]
                    # The first coherent scientific payload is immutable through all later repairs.
                    candidate_locks = validator.repair_locks(value)
                    if state is None and candidate_locks is not None:
                        state = {**candidate_locks, 'previous_response': deepcopy(value)}
                    elif state is not None and candidate_locks is not None:
                        # A formerly illegal action becomes locked as soon as it is legally encoded.
                        if all(value.get(k) == v for k, v in state['locked_fields'].items()):
                            state['locked_fields'].update(deepcopy(candidate_locks['locked_fields']))
                            state['allowed_edit_fields'] = [k for k in state['allowed_edit_fields'] if k not in state['locked_fields']]
                            state['previous_response'] = deepcopy(value)
                    attempt.update(status='contract_invalid', validation_errors=last_errors, parsed_response=value)
                else:
                    outcome = self._valid(value, bindings)
                    attempt.update(status='valid_result', resolved_evidence=bindings, parsed_response=value)
                attempt.update(repair_state=deepcopy(state), wall_seconds=time.monotonic()-start)
                write_json_atomic(directory/f"attempt-{attempt['attempt']:03d}.json", attempt)
                attempts.append(attempt)
            result = {'request': request, 'outcome': outcome, 'outcome_sha256': canonical_sha256(outcome),
                      'attempt_count': len(attempts), 'accounting': {
                          'initial_calls': sum(a['request_kind'] == 'initial' for a in attempts),
                          'schema_repairs': sum(a['request_kind'] == 'schema_repair' for a in attempts),
                          'locator_repairs': sum(a['request_kind'] == 'locator_repair' for a in attempts),
                          'provider_failures': sum(a['status'] == 'provider_failure' for a in attempts),
                          'contract_invalid_attempts': sum(a['status'] == 'contract_invalid' for a in attempts),
                          'first_response_valid': next((a['status'] == 'valid_result' for a in attempts if a['status'] != 'provider_failure'), False)}}
            write_json_atomic(path, result)
        return {'request_sha256': key, 'stage': stage, 'cache_hit': cache_hit, 'actual_calls': actual,
                'receipt': str(path), 'outcome': result['outcome'], 'accounting': result['accounting'],
                'source_binding_status': result['outcome']['source_binding_status']}

    @staticmethod
    def _valid(value, bindings):
        return {'status': 'valid_result', 'value': value, 'resolved_evidence': bindings,
                'source_binding_status': 'validated', 'validation_errors': []}

    @staticmethod
    def _revalidate(outcome, validator):
        if outcome['status'] == 'valid_result':
            try:
                bindings = validator.validate(outcome['value'])
            except (ValueError, RuntimeError) as exc:
                raise RuntimeError('cached v2 scientific response violates its pinned contract') from exc
            if bindings != outcome['resolved_evidence'] or outcome['source_binding_status'] != 'validated':
                raise RuntimeError('cached v2 source bindings differ from pinned public bytes')
        elif outcome['status'] == 'contract_exhausted':
            if outcome['value'] is not None or outcome['source_binding_status'] != 'not_valid':
                raise RuntimeError('exhausted v2 contract was relabeled as scientific success')
        else:
            raise RuntimeError('unknown v2 cached terminal state')
