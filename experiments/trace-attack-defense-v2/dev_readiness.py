"""Apply the authorized dev3 gate to saved, fully checked mechanism reports.

The contract and candidate-funnel percentages use the complete development cohort;
the authorization explicitly makes admission/exposure counts arm-specific. The
per-arm percentage breakdown remains descriptive. No outcome score is consumed.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2'


def read(path):
    return json.loads(path.read_bytes())


def ratio(n, d):
    return n/d if d else 0.0


def decide(subversion):
    root = REPORT/'dev3'/subversion
    paths = {'mechanism': root/'mechanism.json', 'requests': root/'requests.json',
             'integrity': root/'integrity.json', 'phase_a': REPORT/'phase-a'/f'{subversion}-001/result.json'}
    records = {k: read(p) for k, p in paths.items()}
    mechanism, integrity, phase = (records[k] for k in ('mechanism', 'integrity', 'phase_a'))
    if mechanism['completion']['completed'] != 18:
        raise RuntimeError('do not select an incomplete development cohort')
    counts = Counter()
    for arm in mechanism['counts'].values():
        counts.update(arm)
    requests = [r for r in records['requests'] if r['stage'] in {'quality', 'diagnosis', 'application'}]
    applications = [r for r in requests if r['stage'] == 'application']
    denominators = {
        'contract_valid': (sum(r['status'] == 'valid_result' for r in requests), len(requests)),
        'application_contract_valid': (sum(r['status'] == 'valid_result' for r in applications), len(applications)),
        'compiled_reaching_native': (counts['complete_native_candidates'], counts['compiled_candidates']),
        'complete_with_strict_witness': (counts['strict_witness_complete_candidates'], counts['complete_native_candidates']),
    }
    gates = {
        'phase_a_final_recipe': phase['gate_passed'] and phase['method'] == mechanism['method'],
        'saved_contract_and_metadata_integrity': integrity['integrity_passed'] and all(
            integrity[k] == 0 for k in ('illegal_cached_actions', 'host_metadata_mismatches', 'invalid_cached_successes')),
        'contract_valid_at_least_98pct': ratio(*denominators['contract_valid']) >= .98,
        'application_contract_valid_at_least_98pct': ratio(*denominators['application_contract_valid']) >= .98,
        'compiled_reaching_native_at_least_80pct': ratio(*denominators['compiled_reaching_native']) >= .8,
        'complete_with_strict_witness_at_least_60pct': ratio(*denominators['complete_with_strict_witness']) >= .6,
    }
    for arm, values in mechanism['counts'].items():
        exposed = {x['assignment_id'] for x in integrity['active_rule_exposures']
                   if ('user-simulator' in x['assignment_id']) == (arm == 'user')}
        gates[arm+'_at_least_two_online_admitted_assignments'] = values['assignments_with_online_admission'] >= 2
        gates[arm+'_at_least_one_subsequent_turn_online_exposure'] = bool(exposed)
    result = {'method': mechanism['method'], 'full_iteration': mechanism['full_iteration'],
        'readiness_passed': all(gates.values()), 'gates': gates,
        'rates': {k: {'numerator': n, 'denominator': d, 'rate': ratio(n, d)} for k, (n, d) in denominators.items()},
        'source_receipts': {k: {'path': str(p), 'sha256': sha256_file(p)} for k, p in paths.items()},
        'aggregation': 'Contract/candidate-funnel percentages across the complete 18-assignment cohort; admission and exposure minima separately in each 9-assignment arm.',
        'outcome_scores_used': False}
    write_json_atomic(root/'readiness.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('subversion')
    decide(parser.parse_args().subversion)
