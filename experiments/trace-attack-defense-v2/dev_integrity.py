"""Provider-free audit of saved development contracts, host metadata and exposure.

This reporting adapter cannot generate judgments or activate a criterion. It
reconstructs contracts from the request's pinned public bytes and checks every
successful cache entry. No model call is made by this module.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
from types import SimpleNamespace

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evolution_serialization import canonical_sha256
from rubric_gen.submission_revision.trace_defense_evidence_v2 import PublicDocument, native_criterion_payload
from rubric_gen.submission_revision.trace_defense_v2_schema import ResponseContract
from rubric_gen.submission_revision.trace_defense_v2_stage import TraceStagesV2, contract_source_hashes
from rubric_gen.submission_revision.trace_defense_binding import load_binding
from rubric_gen.submission_revision.rubric_generation import RubricPolicy, ElicitedCriterion
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation

ROOT = Path(__file__).resolve().parents[2]
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')


def read(path):
    return json.loads(path.read_bytes())


def restore_document(record):
    """Remove exactly the renderer's address prefix; never normalize source text."""
    lines = record['numbered_text'].splitlines(keepends=True)
    raw = []
    for index, line in enumerate(lines, 1):
        prefix = f'[L{index:06d}] '
        if not line.startswith(prefix):
            raise RuntimeError('saved numbered source differs from the declared renderer')
        raw.append(line[len(prefix):])
    document = PublicDocument(record['source_id'], ''.join(raw))
    if document.model_record() != {k: record[k] for k in document.model_record()}:
        raise RuntimeError('saved numbered source hash, count or rendering differs')
    return document


def restore_contract(request):
    evidence = json.loads(request['evidence'])
    stage = request['stage']
    identity = request['response_contract']
    blind_keys = {
        'quality': {'task', 'pair_id', 'artifact_A', 'artifact_B', 'source_manifest', 'visible_difference'},
        'application': {'task', 'criterion', 'artifact', 'source_manifest'},
        'rubric_view': {'task', 'artifact', 'base_rubric', 'active_penalty_criteria', 'score_minimum', 'score_maximum'},
        'semantic': {'task', 'immutable_base_rubric', 'active_learned_rules', 'replaceable_learned_rules',
                     'rules_already_accepted_this_update', 'allowed_actions', 'proposed_criterion',
                     'replaces', 'public_representation_contract'},
    }
    if stage in blind_keys and set(evidence) != blind_keys[stage]:
        raise RuntimeError('saved blind-stage input shape includes an unapproved evidence channel')
    if stage == 'application' and set(evidence['criterion']) != {'title', 'requirement', 'levels'}:
        raise RuntimeError('application criterion includes unapproved provenance or comparison metadata')
    if stage == 'rubric_view' and set(evidence['artifact']) != {'artifact_id', 'content'}:
        raise RuntimeError('raw rubric view includes a new source-address or private-evidence layer')
    if stage == 'quality':
        records = {x: evidence[x] for x in ('artifact_A', 'artifact_B')}
    elif stage == 'diagnosis':
        records = evidence['public_sources']
    elif stage == 'application':
        records = {'artifact': evidence['artifact']}
    else:
        records = {}
    documents = {k: restore_document(v) for k, v in records.items()}
    if any(set(records[k]) != set(document.model_record()) | {'artifact_id'} for k, document in documents.items()):
        raise RuntimeError('numbered public source has additional unapproved metadata')
    native = {k: v['artifact_id'] for k, v in records.items()}
    active = tuple(x.removeprefix('REPLACE:') for x in identity['allowed_actions'] if x.startswith('REPLACE:'))
    generation = None
    if stage == 'rubric_view':
        generation = SimpleNamespace(elicited_criteria=tuple(
            SimpleNamespace(criterion_id=c['criterion_id'], levels=tuple(
                (level['label'], level.get('points', 0), level['description']) for level in c['levels']))
            for c in evidence['active_penalty_criteria']))
    contract = ResponseContract(stage, request['schema'], documents, native,
                                active_ids=active, labels=tuple(identity['labels']), generation=generation)
    if contract.identity() != identity:
        raise RuntimeError('restored response contract identity differs')
    return contract, evidence


def audit(subversion):
    cohort = RUN/'dev3'/subversion
    completion = read(cohort/'completion.json')
    if completion['completed'] != 18:
        raise RuntimeError('integrity gate requires the complete canonical dev3 cohort')
    counts, rows, metadata, exposure = Counter(), [], [], []
    for assignment in completion['assignments']:
        root = Path(assignment['root'])
        common = {'assignment_id': assignment['assignment_id'], 'root': str(root)}
        public = {}
        for path in sorted((root/'rubric-generations').glob('generation-*/artifact-history.json')):
            for artifact in read(path)['artifacts']:
                if sha256_text(artifact['content']) != artifact['content_sha256']:
                    raise RuntimeError('public history hash differs')
                old = public.setdefault(artifact['artifact_id'], artifact['content'])
                if old != artifact['content']:
                    raise RuntimeError('one native artifact ID names differing bytes')
        for path in sorted((root/'trace-defense-v2-requests').glob('*/result.json')):
            result = read(path)
            request, outcome = result['request'], result['outcome']
            if canonical_sha256(request) != path.parent.name or canonical_sha256(outcome) != result['outcome_sha256']:
                raise RuntimeError('request/outcome hash differs')
            if request['validation_source_sha256s'] != contract_source_hashes():
                raise RuntimeError('use the pinned execution checkout for contract revalidation')
            contract, evidence = restore_contract(request)
            for alias, document in contract.documents.items():
                if public[contract.native_ids[alias]] != document.text:
                    raise RuntimeError('learning source differs from sealed public history')
            TraceStagesV2._revalidate(outcome, contract)
            counts['cache_entries_revalidated'] += 1
            counts[outcome['status']] += 1
            attempts = [read(p) for p in sorted(path.parent.glob('attempt-*.json'))]
            for index, attempt in enumerate(attempts):
                if attempt['request_sha256'] != path.parent.name or attempt['attempt'] != index+1:
                    raise RuntimeError('attempt identity or sequence differs')
                if attempt['status'] == 'valid_result':
                    if index != len(attempts)-1:
                        raise RuntimeError('scientific success followed by additional calls')
                    value = json.loads(attempt['output']['response_text'])
                    if value != outcome['value'] or contract.validate(value) != outcome['resolved_evidence']:
                        raise RuntimeError('cached response differs from the successful attempt')
                    prior = attempts[index-1].get('repair_state') if index else None
                    if prior and any(value.get(k) != v for k, v in prior['locked_fields'].items()):
                        raise RuntimeError('a successful repair changed a locked scientific field')
                counts['attempt_'+attempt['request_kind']] += 1
                counts['attempt_status_'+attempt['status']] += 1
            rows.append({**common, 'stage': request['stage'], 'request_sha256': path.parent.name,
                         'receipt_sha256': sha256_file(path), 'status': outcome['status'],
                         'source_count': len(contract.documents), 'contract_revalidated': True})
        for path in sorted((root/'rubric-generations').glob('generation-*/criterion-proposal.json')):
            generation = int(path.parent.name.split('-')[-1])
            if generation < 2:
                continue
            proposal = read(path)
            diagnoses = {x['pair_id']: x for x in proposal['diagnoses']}
            prior = load_rubric_generation(root, generation-1, expected_policy=RubricPolicy.RED_TEAM_TRACE)
            native = read(path.parent/'aggregate-margins.json')
            decisions = {r['criterion_id']: r for r in native['decisions']}
            compilations = {r['pair_id']: r['response'] for r in proposal['compilations']}
            accepted, reserved = [], set()
            seen_content = {r.criterion_id for r in prior.elicited_criteria}
            for diagnostic in proposal['diagnoses']:
                available = [r.criterion_id for r in prior.elicited_criteria if r.criterion_id not in reserved]
                if diagnostic['available_ids'] != available or diagnostic['accepted_this_update'] != accepted:
                    raise RuntimeError('diagnosis replacement registry differs from real active/admitted lineage')
                compiled = compilations.get(diagnostic['pair_id'])
                if not compiled or not compiled['criteria']:
                    continue
                raw = native_criterion_payload(compiled['criteria'][0], witness_pair_id=diagnostic['pair_id'],
                    action=diagnostic['response']['action'], active_learned_ids=available)
                criterion = ElicitedCriterion.create(title=raw['title'], requirement=raw['requirement'],
                    levels=tuple((x['label'], {'A': 0, 'B': -5, 'C': -10}[x['label']], x['description']) for x in raw['levels']),
                    provenance_pair_ids=tuple(raw['provenance_pair_ids']), source_generation=generation)
                cid = criterion.criterion_id
                if cid in seen_content:
                    continue
                seen_content.add(cid)
                if decisions.get(cid, {}).get('accepted'):
                    accepted.append(cid)
                    reserved.update(raw['replaces'])
            if accepted != native['accepted_candidate_ids']:
                raise RuntimeError('accepted-rule order differs from prospective diagnosis/compilation order')
            counts['operation_registries_revalidated'] += len(proposal['diagnoses'])
            expected = []
            for compiled in proposal['compilations']:
                response = compiled['response']
                if not response or not response['criteria']:
                    continue
                diagnosis = diagnoses[compiled['pair_id']]
                payload = native_criterion_payload(response['criteria'][0], witness_pair_id=compiled['pair_id'],
                    action=diagnosis['response']['action'], active_learned_ids=diagnosis['available_ids'])
                expected.append(payload)
                metadata.append({**common, 'generation': generation, 'witness_pair_id': compiled['pair_id'],
                                 'action': diagnosis['response']['action'], 'metadata_match': True})
            if expected != proposal['criteria']:
                raise RuntimeError('host-owned witness/replacement metadata differs from compiled content')
            counts['compiled_metadata_revalidated'] += len(expected)
        for path in sorted((root/'submission-rubric-bindings').glob('s*.json')):
            binding = load_binding(root, path.stem)
            counts['submission_bindings_revalidated'] += 1
            if not binding['feedback_opportunity']:
                continue
            turn = binding['solver_turn']
            prompt_path = root/'turns'/f'turn-{turn:03d}'/'prompt.txt'
            if not prompt_path.is_file():
                raise RuntimeError('binding lacks its native subsequent solver prompt')
            reminder = read(root/'trace-defense-reminders'/f'{path.stem}.json')
            if sha256_file(prompt_path) != reminder['final_prompt_sha256']:
                raise RuntimeError('delivery receipt differs from the actual solver prompt')
            prompt = prompt_path.read_text()
            block = reminder['message_component']
            if block and not prompt.endswith('\n\n'+block):
                raise RuntimeError('focused component does not match the final prompt suffix')
            ordinary = prompt[:-len('\n\n'+block)] if block else prompt
            if sha256_text(ordinary) != reminder['ordinary_prompt_sha256']:
                raise RuntimeError('ordinary feedback component hash differs')
            generation = load_rubric_generation(root, binding['active_generation_round'],
                                                 expected_policy=RubricPolicy.RED_TEAM_TRACE)
            selection = reminder['selection']
            for criterion in generation.elicited_criteria:
                if criterion.source_generation < 2:
                    continue
                focused = bool(selection and selection['criterion_id'] == criterion.criterion_id)
                ordinary_offset = ordinary.find(criterion.requirement)
                escaped_offset = ordinary.find(json.dumps(criterion.requirement, ensure_ascii=False)[1:-1])
                ordinary_exposed = ordinary_offset >= 0 or escaped_offset >= 0
                if focused or ordinary_exposed:
                    exposure.append({**common, 'criterion_id': criterion.criterion_id,
                        'source_generation': criterion.source_generation, 'solver_turn': turn,
                        'active_generation': generation.generation_round, 'focused': focused,
                        'ordinary_verbatim': ordinary_offset >= 0,
                        'ordinary_json_escaped': ordinary_offset < 0 and escaped_offset >= 0,
                        'prompt': str(prompt_path),
                        'prompt_sha256': sha256_file(prompt_path), 'binding_sha256': binding['binding_sha256']})
    out = ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2/dev3'/subversion
    out.mkdir(parents=True, exist_ok=True)
    result = {'method': completion['method'], 'counts': dict(counts), 'integrity_passed': True,
              'illegal_cached_actions': 0, 'host_metadata_mismatches': 0, 'invalid_cached_successes': 0,
              'provider_calls': 0, 'requests': rows, 'metadata': metadata, 'active_rule_exposures': exposure}
    write_json_atomic(out/'integrity.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'requests', 'metadata', 'active_rule_exposures'}}), flush=True)


if __name__ == '__main__':
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('read saved compute artifacts through Slurm')
    parser = argparse.ArgumentParser()
    parser.add_argument('subversion')
    audit(parser.parse_args().subversion)
