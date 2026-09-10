"""Bounded requests with exact cross-generation reuse and explicit paid-call receipts."""
from dataclasses import asdict
from pathlib import Path
import threading
import time
import jsonschema
from rubric_gen.artifacts.serialization import write_json_atomic
from .evolution_serialization import canonical_json, canonical_sha256, load_json_object
from .evolution_provider import RubricProposerProviderError, RubricProposerInputLimitError, StructuredProviderOutput
from .evolution_stage import PROVIDER_FAILURE_MAX_RETRIES, maximum_stage_attempts
from .trace_defense_prompts import STAGES, VERSION, prompt_hashes

class TraceStages:
    def __init__(self, proposer, root: Path, *, read_only=False):
        self.proposer, self.root, self.read_only = proposer, root, read_only
        self.records, self.lock = [], threading.Lock()

    def call(self, stage, evidence, schema, validate=None):
        contract = self.proposer.proposer_contract
        request = {'red_team_trace_version': VERSION, 'stage': stage, 'prompt': STAGES[stage],
                   'prompt_sha256': prompt_hashes()[stage], 'evidence': canonical_json(evidence),
                   'schema': schema, 'provider': contract.record(), 'max_retries': self.proposer.max_retries,
                   'provider_failure_max_retries': PROVIDER_FAILURE_MAX_RETRIES}
        key = canonical_sha256(request)
        directory = self.root / key
        path = directory / 'result.json'
        if path.is_file():
            result = load_json_object(path.read_text(), 'trace request receipt')
            if result['request'] != request or canonical_sha256(result['outcome']) != result['outcome_sha256']:
                raise RuntimeError('trace request receipt changed')
            record = {'request_sha256': key, 'stage': stage, 'cache_hit': True,
                      'actual_calls': 0, 'receipt': str(path), 'outcome': result['outcome']}
        else:
            if self.read_only:
                raise RuntimeError('completed trace generation is missing an exact request receipt')
            directory.mkdir(parents=True, exist_ok=True)
            previous = [load_json_object(p.read_text(), 'trace attempt') for p in sorted(directory.glob('attempt-*.json'))]
            if any(p.get('request_sha256') != key or p.get('attempt') != i + 1
                   for i, p in enumerate(previous)):
                raise RuntimeError('trace attempt identity or sequence changed')
            if any(p.get('permanent') for p in previous):
                raise RubricProposerProviderError(f'{stage}: retained permanent provider failure at {directory}')
            provider_failures = sum(p['status']=='provider_failure' for p in previous)
            invalid = sum(p['status']=='invalid_response' for p in previous)
            repair = previous[-1].get('error') if previous and previous[-1]['status']=='invalid_response' else None
            outcome, actual = None, 0
            attempts = list(previous)
            # A crash after the successful attempt was sealed but before result.json
            # must never buy another scientific judgment for the same request.
            successful = [p for p in previous if p['status'] == 'valid_response']
            if successful:
                if len(successful) != 1 or previous[-1] is not successful[0]:
                    raise RuntimeError('trace attempt history continued after a valid response')
                output = StructuredProviderOutput(**successful[0]['output'])
                contract.validate_output(output)
                value = load_json_object(output.response_text, stage)
                jsonschema.validate(value, schema)
                if validate:
                    validate(value)
                outcome = {'value': value, 'fallback_reason': None}
            while outcome is None and len(attempts) < maximum_stage_attempts(self.proposer.max_retries) and invalid < self.proposer.max_retries + 1:
                if provider_failures > PROVIDER_FAILURE_MAX_RETRIES:
                    raise RubricProposerProviderError(f'{stage}: bounded provider attempts exhausted; retained at {directory}')
                attempt_evidence = request['evidence']
                if repair:
                    attempt_evidence += '\n\n<repair>\nThe prior response failed validation.\n' + repair + '\nReturn a complete corrected response.\n</repair>'
                start = time.monotonic()
                attempt = {'request_sha256': key, 'stage': stage, 'attempt':len(attempts)+1,
                           'evidence_sha256': canonical_sha256(attempt_evidence)}
                actual += 1
                try:
                    # Native injected provider remains available for structural tests.
                    operation = self.proposer.run_proposer
                    if getattr(operation, '__func__', None) is self.proposer._run_direct_proposer.__func__:
                        output = contract.generate(instructions=STAGES[stage], evidence=attempt_evidence,
                                                   response_schema=schema, request_context=VERSION,
                                                   schema_name='trace_defense_' + stage)
                    else:
                        output = operation(stage=stage, evidence=attempt_evidence, response_schema=schema)
                except RubricProposerInputLimitError:
                    raise
                except Exception as exc:
                    provider_failures += 1
                    attempt.update(status='provider_failure', error=str(exc), error_type=type(exc).__name__)
                    status = getattr(exc,'status_code',None); code = getattr(exc,'code',None)
                    attempt['permanent'] = status in {400,401,403,404,422} or code in {'insufficient_quota','invalid_api_key'}
                    attempt['wall_seconds'] = time.monotonic()-start
                    write_json_atomic(directory/f"attempt-{attempt['attempt']:03d}.json",attempt)
                    attempts.append(attempt)
                    if attempt['permanent'] or provider_failures > PROVIDER_FAILURE_MAX_RETRIES:
                        raise RubricProposerProviderError(f'{stage}: provider failed; receipt {directory}') from exc
                    time.sleep(min(.5*2**(provider_failures-1),8))
                    continue
                attempt['output'] = asdict(output)
                try:
                    contract.validate_output(output)
                    value = load_json_object(output.response_text, stage)
                    jsonschema.validate(value, schema)
                    if validate:
                        validate(value)
                except (ValueError, RuntimeError, jsonschema.ValidationError) as exc:
                    invalid += 1; repair = str(exc)
                    attempt.update(status='invalid_response', error=repair)
                else:
                    outcome = {'value': value, 'fallback_reason': None}
                    attempt['status'] = 'valid_response'
                attempt['wall_seconds'] = time.monotonic()-start
                write_json_atomic(directory/f"attempt-{attempt['attempt']:03d}.json",attempt)
                attempts.append(attempt)
                if outcome is not None:
                    break
            if outcome is None:
                if provider_failures and invalid < self.proposer.max_retries+1:
                    raise RubricProposerProviderError(f'{stage}: bounded provider attempts exhausted at {directory}')
                outcome = {'value':None, 'fallback_reason': repair or 'schema attempts exhausted'}
            result = {'request':request, 'outcome':outcome, 'outcome_sha256':canonical_sha256(outcome),
                      'attempt_count':len(attempts)}
            write_json_atomic(path,result)
            record = {'request_sha256':key, 'stage':stage, 'cache_hit':bool(successful),
                      'actual_calls':actual, 'receipt':str(path), 'outcome':outcome}
        with self.lock:
            self.records.append(record)
        return record['outcome']['value']
