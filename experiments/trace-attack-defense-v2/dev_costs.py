"""Saved development usage accounting. No provider calls or outcome evaluation."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.detection.costs import usage_tokens, request_cost
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.pricing import PRICING_AS_OF

ROOT = Path(__file__).resolve().parents[2]
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')
REPORT = ROOT/'docs/reports/2026-09-10/trace-attack-defense-v2'


def read(path):
    return json.loads(path.read_bytes())


def response(stage, generation, path, **extra):
    provider = generation['provider']
    usage = generation.get('usage') or generation.get('raw_usage') or generation.get('provider_metadata', {}).get('usage')
    tokens = usage_tokens(SimpleNamespace(provider=provider, provider_metadata={'usage': usage}))
    model = generation['requested_model']
    return {'stage': stage, 'model': model, 'response_id': generation.get('response_id'), 'receipt': str(path),
            'tokens': tokens, 'estimated_usd': request_cost(model, **tokens) if tokens else None, **extra}


def stage_summary(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['stage']].append(row)
    result = {}
    for stage, values in groups.items():
        fresh = [v for v in values if not v.get('reused_frozen')]
        result[stage] = {'returned_responses': len(values), 'reused_frozen': len(values)-len(fresh),
                        'fresh_responses': len(fresh), 'usage_available': sum(v['tokens'] is not None for v in fresh),
                        'tokens': dict(sum((Counter(v['tokens'] or {}) for v in fresh), Counter())),
                        'estimated_usd': sum(v['estimated_usd'] or 0 for v in fresh),
                        'attempt_wall_seconds': sum(v.get('wall_seconds', 0) for v in fresh)}
    return result


def direct_attempts(paths):
    rows, failures = [], []
    for path in paths:
        attempt = read(path)
        output = attempt.get('output')
        if output:
            rows.append(response(attempt['stage'], output['generation'], path,
                                 kind=attempt['request_kind'], status=attempt['status'],
                                 wall_seconds=attempt['wall_seconds'], native_cost=output['cost']))
        else:
            failures.append({'receipt': str(path), 'status': attempt['status'],
                             'error_type': attempt.get('error_type'), 'wall_seconds': attempt['wall_seconds']})
    return rows, failures


def agent_usage(paths, stage):
    threads, events = {}, Counter()
    for path in paths:
        thread = str(path)
        for line in path.open():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            events[event.get('type', 'unknown')] += 1
            if event.get('type') == 'thread.started' and event.get('thread_id'):
                thread = event['thread_id']
            if event.get('type') != 'turn.completed' or not isinstance(event.get('usage'), dict):
                continue
            entry = threads.setdefault(thread, {'stage': stage, 'thread_id': thread, 'usage': {}, 'estimated_usd_lower_bound': 0})
            for key, value in event['usage'].items():
                if type(value) is int:
                    entry['usage'][key] = max(entry['usage'].get(key, 0), value)
            cost = RunCost.from_event(event, model='gpt-5.6-luna')
            entry['estimated_usd_lower_bound'] = max(entry['estimated_usd_lower_bound'], cost.estimated_cost_usd or 0)
    return list(threads.values()), {'events': dict(events), 'threads_with_usage': len(threads),
        'tokens': dict(sum((Counter(t['usage']) for t in threads.values()), Counter())),
        'estimated_usd_lower_bound': sum(t['estimated_usd_lower_bound'] for t in threads.values())}


def capacity_receipts(owners):
    """Account only this cohort's jobs in the shared coordinator journal."""
    jobs = {str(o['job']) for o in owners}
    hosts = {o['host'] for o in owners}
    earliest = min(datetime.fromisoformat(o['time']).timestamp() for o in owners)
    events = []
    coordinator = Path('/home/aydanh/repos/rubric_gen/runs/.runtime-babel')
    for host in hosts:
        for path in coordinator.glob(f'events-{host}-*.jsonl'):
            if path.stat().st_mtime < earliest:
                continue
            for line in path.open():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if str(event.get('job_id')) in jobs:
                    events.append(event)
    operations = defaultdict(list)
    leases = {}
    active = maximum = 0
    for event in sorted(events, key=lambda e: e['time']):
        if event['event'].startswith('operation_'):
            operations[event['operation']].append(event)
        if event.get('kind') != 'provider':
            continue
        if event['event'] == 'acquired':
            leases[event['lease_id']] = event
            active += event['slots']
            maximum = max(maximum, active)
        elif event['event'] == 'released':
            active -= event['slots']
    summary = {'jobs': sorted(jobs), 'maximum_owned_provider_leases': maximum,
        'provider_leases_acquired': len(leases), 'provider_wait_seconds': sum(e['wait_seconds'] for e in leases.values()),
        'audit_wait_seconds': sum(e.get('wait_seconds', 0) for e in events if e.get('kind') == 'audit' and e['event'] == 'acquired'),
        'operations': {k: {'event_counts': dict(Counter(e['event'] for e in values)),
                           'elapsed_seconds': sum(e.get('elapsed_seconds', 0) for e in values)}
                       for k, values in operations.items()},
        'note': 'Native operations may be nested; summed operation durations are not independent API-call counts.'}
    return events, summary


def save(public, raw_root, summary, raw):
    public.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    path = raw_root/'cost-records.json'
    write_json_atomic(path, raw)
    summary.update(pricing_registry_date=PRICING_AS_OF,
        raw_records={'path': str(path), 'sha256': sha256_file(path), 'bytes': path.stat().st_size},
        limitations=['Usage estimates use the frozen repository pricing registry, not provider invoices.',
                     'Calls failing without returned usage have unknown token cost.',
                     'Agent thread usage is cumulative: maximum totals per thread are used across resumed turns.',
                     'Internal agent model-request counts are unavailable; agent invocations and structured requests are distinct.',
                     'Summed request wall times include waiting and concurrency; they are not cohort elapsed time.',
                     'Frozen dev3 seed/paraphrase production costs are excluded and their reuse is disclosed.'])
    write_json_atomic(public/'costs.json', summary)
    print(json.dumps(summary), flush=True)


def phase_a(subversion):
    cohort = RUN/'phase-a'/f'{subversion}-001'
    result = read(cohort/'result.json')
    rows, failures = direct_attempts(cohort.glob('requests/*/attempt-*.json'))
    save(REPORT/'phase-a'/f'{subversion}-001', cohort/'report',
         {'scope': 'phase_a', 'method': result['method'], 'logical_requests': len(result['rows']),
          'direct_attempts': len(rows)+len(failures), 'provider_failure_attempts': len(failures),
          'stage_summary': stage_summary(rows), 'elapsed_seconds': result['wall_seconds']},
         {'responses': rows, 'failures': failures})


def dev3(subversion):
    cohort = RUN/'dev3'/subversion
    completion = read(cohort/'completion.json')
    roots = [Path(a['root']) for a in completion['assignments']]
    seed_ids = set()
    for task in ('da-3-4', 'da-11-1', 'da-18-1'):
        for path in (RUN/'dev3/inputs'/task/'seed').glob('**/usage.json'):
            seed_ids.add((read(path).get('call') or {}).get('response_id'))
    rows, failures = direct_attempts(p for root in roots for p in (root/'trace-defense-v2-requests').glob('*/attempt-*.json'))
    seen = {r['response_id'] for r in rows if r['response_id']}
    for root in roots:
        for path in (root/'judgments').glob('**/usage.json'):
            generation = read(path).get('call') or {}
            identity = generation.get('response_id')
            if identity and identity not in seen:
                seen.add(identity)
                rows.append(response('optimizer_judge', generation, path, reused_frozen=identity in seed_ids))
        for directory in ('feedback-generations', 'feedback-history-summaries'):
            for path in (root/directory).glob('**/*.json'):
                value = read(path)
                generation = value.get('feedback_generation') or value.get('summary_generation') or value.get('generation')
                if not isinstance(generation, dict) or not generation.get('response_id') or generation['response_id'] in seen:
                    continue
                seen.add(generation['response_id'])
                rows.append(response('common_simulator_summary' if 'summaries' in directory else 'common_simulator', generation, path))
    # Real native g1 producer caches are counted once, never assignment-installed copies.
    g1 = read(cohort/'frozen-g1.json')
    for receipt in g1:
        generation_root = Path(receipt['manifest']).parents[2]
        for path in (generation_root/'rubric-proposer-records').glob('*.json'):
            value = read(path)
            generation = value['output']['generation']
            if generation.get('response_id') in seen:
                continue
            seen.add(generation.get('response_id'))
            rows.append(response('dev3_offline_g1_'+value['request']['stage'], generation, path))
    agents, summaries = [], {}
    for stage, dirname, pattern in [('sidecar', 'red-team', 'checkpoint-*/trajectory.stream.jsonl'),
                                   ('solver', 'turns', 'turn-*/trajectory.stream.jsonl')]:
        data, summary = agent_usage([p for root in roots for p in (root/dirname).glob(pattern)], stage)
        agents.extend(data)
        summaries[stage] = summary
    owners = [read(p) for p in (cohort/'owners').glob('*/launch.json')]
    first = min(datetime.fromisoformat(o['time']).timestamp() for o in owners)
    capacity_events, capacity = capacity_receipts(owners)
    save(REPORT/'dev3'/subversion, cohort/'report',
         {'scope': 'full_dev3_iteration', 'method': completion['method'], 'completed': completion['completed'],
          'direct_returned_responses': len(rows), 'learning_provider_failures': len(failures),
          'stage_summary': stage_summary(rows), 'agent_summary': summaries,
          'owner_jobs': [o['job'] for o in owners], 'elapsed_seconds': (cohort/'completion.json').stat().st_mtime-first,
          'auditor_calls': 0, 'capacity': capacity},
         {'responses': rows, 'failures': failures, 'agent_threads': agents, 'capacity_events': capacity_events})


if __name__ == '__main__':
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('compute storage requires Slurm')
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['phase_a', 'dev3'])
    parser.add_argument('subversion')
    args = parser.parse_args()
    (phase_a if args.phase == 'phase_a' else dev3)(args.subversion)
