"""Offline completion checks and API accounting for the approved new30 audit."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path

from prepare import HERE, ROOT, OUTPUT
from run_audit import proxy


def read(path):
    return json.loads(path.read_text())


def generation_check(generation, model):
    assert generation['effective_model'] == generation['requested_model'] == model
    assert generation['request_parameters']['reasoning_effort'] == 'high'


def report():
    audit_run = OUTPUT/'audit-run'
    receipt = read(sorted((audit_run/'invocations').glob('*/receipt.json'))[-1])
    assert receipt['status'] == 'completed' and receipt['exit_code'] == 0
    audit = OUTPUT/'audits'/receipt['experiment_id']
    study = read(OUTPUT/'studies'/receipt['experiment_id']/'study.json')
    assert len(study['records']) == 720 and all(r['status']=='completed' for r in study['records'])
    assert set(Counter(r['condition_id'] for r in study['records']).values()) == {90}
    coverage = {}
    costs = {}
    for stage, expected, model in [('rubric_score',4334,'gpt-6-luna'),
                                   ('absolute_score',807,'gpt-6-sol'),
                                   ('pairwise_preference',719,'gpt-6-sol')]:
        folder = audit/stage
        summary = read(folder/'summary.json')
        assert summary['status'] == 'completed' and summary['models'] == [model]
        assert not summary['missing_models'] and not summary['judge_failures']
        assert summary['planned_semantic_judgment_count'] == summary['successful_semantic_judgment_count'] == expected
        assert summary['assignment_coverage']['evaluated_assignment_count'] == 720
        records = [read(p) for p in (folder/'records').glob('*.json')]
        assert len(records) == expected and all(r['model']==model for r in records)
        if stage == 'rubric_score':
            assert all(r['reference_scores']['holdout'][phase]['variant_count']==3
                       for r in summary['assignments'] for phase in ('initial','final'))
            usages = [read(p)['call'] for p in (folder/'artifacts').rglob('usage.json')]
            assert len(usages) == expected
            for usage in usages:
                assert usage['requested_model']==usage['effective_model']==model
                assert usage['request_parameters']['reasoning_effort']=='high'
            costs[stage] = sum(proxy.actual_cost(model, u['raw_usage']) for u in usages)
        else:
            for record in records:
                generation_check(record['generation'], model)
            costs[stage] = sum(proxy.actual_cost(model, r['generation']['provider_metadata']['usage']) for r in records)
        coverage[stage] = expected
    for window in ('full_trajectory','post_update','final_revision','final_artifact'):
        folders = list((audit/f'direct_{window}').glob('evaluations/*'))
        assert len(folders) == 1
        folder = folders[0]
        summary = read(folder/'summary.json')
        assert summary['models'] == ['gpt-6-luna']
        records = summary['records']
        assert len(records)==720 and len({r['source_path'] for r in records})==720
        assert all(r['status'] in {'completed','skipped'} and r['model']=='gpt-6-luna' for r in records)
        scores = list(folder.glob('cases/*/gpt-6-luna/score.json'))
        assert len(scores)==720
        successful_cost = 0.
        for path in scores:
            for chunk in path.parent.glob('chunk-*'):
                attempts = [read(p) for p in chunk.glob('attempt-*.json')]
                generations = [a['generation'] for a in attempts if a.get('generation')]
                assert generations
                for generation in generations:
                    generation_check(generation, 'gpt-6-luna')
                    successful_cost += proxy.actual_cost('gpt-6-luna',generation['provider_metadata']['usage'])
                request = attempts[-1]['identity']['request']
                assert 'Answer-only task guidance:' in request['instructions']
        coverage[window] = {'records':720, 'decisions':dict(Counter(r['verdict']['decision'] for r in records))}
        costs[window] = successful_cost
    events = [json.loads(line) for line in (audit_run/'cost-events.jsonl').read_text().splitlines()]
    known = [e for e in events if e['usage_known']]
    unknown = [e for e in events if not e['usage_known']]
    budget = read(audit_run/'budget.json')
    known_cost = sum(e['cost_usd'] for e in known)
    reserved = sum(e['cost_usd'] for e in unknown)
    assert not budget['pending']
    assert abs(known_cost-budget['known_usage_cost_usd'])<1e-7
    assert abs(reserved-budget['unknown_usage_reserved_usd'])<1e-7
    assert abs(known_cost+reserved-budget['spent_usd'])<1e-7
    models = Counter(e['usage']['model'] for e in known)
    assert set(models) == {'gpt-6-luna','gpt-6-sol'}
    manifest = read(HERE/'manifest50.json')
    sources = [r['source_id'] for r in manifest['retained20']+manifest['extension30']]
    assert len(sources)==len(set(sources))==50
    for root,eid in [('healthbench-hard-challenge20-local-20260926','healthbench-hard-factorial-r3-01eb8a5a9277'),
                     ('healthbench-hard-result20-semi-score-20260926','healthbench-hard-factorial-r3-ba842ae5e275')]:
        old = ROOT/'runs'/root
        old_study = read(old/'studies'/eid/'study.json')
        assert len(old_study['records'])==240 and all(r['status']=='completed' for r in old_study['records'])
        for stage in ('rubric_score','absolute_score','pairwise_preference'):
            summary=read(old/'audits'/eid/stage/'summary.json')
            assert summary['status']=='completed' and not summary['missing_models'] and not summary['judge_failures']
        rh_root=old/'rh-answer-only-v2' if root.startswith('healthbench-hard-challenge20') else old/'audits'/eid
        for window in ('full_trajectory','post_update','final_revision','final_artifact'):
            summaries=list((rh_root/f'direct_{window}').glob('evaluations/*/summary.json'))
            assert len(summaries)==1
            records=read(summaries[0])['records']
            assert len(records)==240 and all(r['status']=='completed' for r in records)
    first_receipt=read(sorted((audit_run/'invocations').glob('*/receipt.json'))[0])
    elapsed=(datetime.fromisoformat(receipt['ended_utc'])-datetime.fromisoformat(first_receipt['started_utc'])).total_seconds()/60
    result=dict(status='completed',coverage=coverage,unique_judgments=8740,
                total_tasks=50,total_assignments=1200,assignments_per_condition=150,
                successful_output_token_costs_by_stage=costs,known_api_token_cost_usd=known_cost,
                unknown_usage_count=len(unknown),unknown_usage_reserved_usd=reserved,
                conservative_ledger_usd=budget['spent_usd'],known_response_count=len(known),
                model_responses=dict(models),elapsed_minutes=elapsed,
                estimate_usd=25,planning_range_usd=[20,30],
                cost_caveat='Known token charges include recorded retries and reasoning/cache charges; unknown reservations are not an invoice. No billing dashboard reconciliation performed.',
                receipt=receipt)
    lines=['# HealthBench Hard Result50 — remaining audit complete','',
           '50 tasks × eight conditions × three replicates:1200 trajectories/audits (150 per condition). '
           'Only the new30-task audits were dispatched; solver and retained20 were reused.','',
           '| New30 stage | Unique judgments | Model / effort |','|---|---:|---|',
           '| Rubric S/H/original/active |4334|6Luna high|',
           '| A |807|6Sol high|','| Pairwise |719|6Sol high|',
           '| RH:four windows |2880 (720 each)|6Luna high; corrected answer-only guidance|','',
           f'Recorded new audit API token charges: **${known_cost:.6f}**; forecast$25 (range$20–30).',
           f'Unknown usage:{len(unknown)} requests, conservative reservation **${reserved:.6f}**, not asserted as actual fees.',
           f'Conservative ledger:${budget["spent_usd"]:.6f}; pending0. Elapsed:{elapsed:.1f} minutes.','',
           'All terminal summaries, unique record coverage, three heldout variants, raw model/high-effort usage, '
           'four RH windows and separate cost accounting verified. Decisions/abstentions are retained without relabeling.','',
           'The token ledger is not an independently verified provider invoice. See audit-completion.json for coverage and provenance.']
    (OUTPUT/'audit-completion.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUTPUT/'AUDIT_COMPLETE.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='receipt'},indent=2))


if __name__ == '__main__':
    report()
