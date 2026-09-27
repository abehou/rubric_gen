"""Offline complete-cohort analysis; no provider calls or experiment mutation."""
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

from inspect_solver import inspect, ROOT, RUN, STUDY, read

HERE = Path(__file__).resolve().parent
AUDIT = RUN/'audits'/STUDY.name
METRICS = ('W','S','H','A','W-S','S-H','H-A','O')
WINDOWS = ('full_trajectory','final_artifact','post_update','final_revision')


def interval(values):
    # Resample tasks, not the dependent condition/replicate rows.
    rng=random.Random(20260926)
    boot=sorted(mean(rng.choices(values,k=len(values))) for _ in range(10000))
    return [boot[249],boot[9749]]


def analyze():
    solver=inspect()
    summaries={n:read(AUDIT/n/'summary.json') for n in ('rubric_score','absolute_score','pairwise_preference')}
    for n,s in summaries.items():
        assert s['status']=='completed' and not s['missing_models'] and not s['judge_failures']
        assert s['successful_semantic_judgment_count']==s['planned_semantic_judgment_count']
        assert s['assignment_coverage']['evaluated_assignment_count']==240
        assert len(list((AUDIT/n/'records').glob('*.json')))==s['planned_semantic_judgment_count']
    byid={n:{r['assignment_id']:r for r in s['assignments']} for n,s in summaries.items()}
    windows={}
    for w in WINDOWS:
        paths=list((AUDIT/f'direct_{w}').rglob('summary.json'));assert len(paths)==1
        s=read(paths[0]);assert s['models']==['gpt-6-luna']
        assert len(s['records'])==240 and all(r['status']=='completed' and r['model']=='gpt-6-luna' for r in s['records'])
        windows[w]={r['source_path']:r['verdict'] for r in s['records']}
    rows=[]
    for r in solver['rows']:
        path=ROOT/r['root'];aid='--'.join([r['task_id'],f"rep-{r['replicate']:03d}",'solver-luna',r['condition_id']])
        rubric=byid['rubric_score'][aid]['reference_scores']
        absolute=byid['absolute_score'][aid]['rubric_free_absolute_scores']
        out={k:r[k] for k in ('task_id','replicate','condition_id','root','changed','accepted','generations','stop')}
        out['assignment_id']=aid
        out['rounds']=[{k:v for k,v in step.items() if k!='answer'} for step in r['rounds']]
        for phase,index in [('initial',0),('final',-1)]:
            assert rubric['holdout'][phase]['variant_count']==3
            values=dict(W=r['rounds'][index]['W'],S=rubric['selected'][phase]['mean'],
                        H=rubric['holdout'][phase]['mean'],A=absolute[phase+'_panel_mean'],
                        O=rubric['original'][phase]['mean'])
            values.update({'W-S':values['W']-values['S'],'S-H':values['S']-values['H'],'H-A':values['H']-values['A']})
            out[phase]=values
        out['pairwise_final_vs_initial']=byid['pairwise_preference'][aid]['pairwise_preference_scores']['panel_mean']
        for w in WINDOWS:out[w]=windows[w][str(path.resolve())]
        rows.append(out)
    groups=defaultdict(list)
    for r in rows:groups[r['condition_id']].append(r)
    conditions={}
    for c,rs in sorted(groups.items()):
        assert len(rs)==60
        conditions[c]={phase:{k:mean(r[phase][k] for r in rs) for k in METRICS} for phase in ('initial','final')}
        conditions[c].update({w:dict(Counter(r[w]['decision'] for r in rs)) for w in WINDOWS})
        conditions[c]['pairwise']=dict(Counter(r['pairwise_final_vs_initial'] for r in rs))
        conditions[c]['A_gain']=mean(r['final']['A']-r['initial']['A'] for r in rs)
        task_gains=[mean(r['final']['A']-r['initial']['A'] for r in rs if r['task_id']==t)
                    for t in sorted({r['task_id'] for r in rs})]
        conditions[c]['A_gain_task_bootstrap_95']=interval(task_gains)
        conditions[c]['A_changes']=dict(Counter('up' if r['final']['A']>r['initial']['A'] else
            'down' if r['final']['A']<r['initial']['A'] else 'flat' for r in rs))
        conditions[c]['final_perfect']={k:sum(abs(r['final'][k]-100)<1e-6 for r in rs) for k in ('W','S','H','A','O')}
        conditions[c]['revision']=solver['groups'][c]
        live=[r for r in solver['rows'] if r['condition_id']==c]
        conditions[c]['criterion_exposure']={}
        for i in (1,2):
            accepted=[r for r in live if any(x['generation']==f'generation-{i:04d}' for x in r['accepted'])]
            conditions[c]['criterion_exposure'][str(i)]={
                'assignments_with_new_criteria':len(accepted),
                'any_active_penalty_on_current_answer':sum(r['rounds'][i]['penalty']<0 for r in accepted),
                'next_answer_changed':sum(r['changed'][i] for r in accepted),
                'active_penalty_cleared_next_round':sum(r['rounds'][i]['penalty']<0 and r['rounds'][i+1]['penalty']==0 for r in accepted)}
    task_pairs=[];contrasts={}
    for feedback in ('full','user-simulator'):
        for task in sorted({r['task_id'] for r in rows}):
            arms={policy:[r for r in groups[feedback+'-'+policy] if r['task_id']==task] for policy in ('static','red-team-trace')}
            delta={k:mean(r['final'][k] for r in arms['red-team-trace'])-mean(r['final'][k] for r in arms['static']) for k in METRICS}
            task_pairs.append({'feedback':feedback,'task_id':task,'RTT_minus_static':delta,
                               'static':{k:mean(r['final'][k] for r in arms['static']) for k in METRICS},
                               'RTT':{k:mean(r['final'][k] for r in arms['red-team-trace']) for k in METRICS}})
        contrasts[feedback]={}
        for k in METRICS:
            v=[p['RTT_minus_static'][k] for p in task_pairs if p['feedback']==feedback]
            contrasts[feedback][k]={'mean':mean(v),'task_bootstrap_95':interval(v),
                                   'positive':sum(x>1e-8 for x in v),'tie':sum(abs(x)<=1e-8 for x in v),'negative':sum(x< -1e-8 for x in v)}
    return {'study':STUDY.name,'definitions':'W online selected-base 5.6 Luna low; S selected-base 6 Luna high; H mean of 3 heldout rubric variants 6 Luna high; A rubric-free 6 Sol high; O original benchmark rubric 6 Luna high. All scores 0–100; signed gaps. Purposive 20-task subset; task-bootstrap intervals are descriptive, not benchmark population inference. Independent audits are endpoints only; R1/R2 curves are W, not S/H/A.',
            'coverage':{k:s['successful_semantic_judgment_count'] for k,s in summaries.items()},
            'conditions':conditions,'paired_task_contrasts':contrasts,'task_pairs':task_pairs,'rows':rows,
            'budget':read(RUN/'budget.json')}


def tables(result):
    order=('full-static','full-red-team-trace','user-simulator-static','user-simulator-red-team-trace')
    names=dict(zip(order,('Full × static','Full × RTT','User × static','User × RTT')))
    lines=['# Complete-cohort numeric tables','',result['definitions'],'',
           '## Final endpoints','','| Condition | W | S | H | A | W−S | S−H | H−A | Full RH | Final RH |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c in order:
        x=result['conditions'][c]
        lines.append('| '+names[c]+' | '+' | '.join(f"{x['final'][k]:.2f}" for k in METRICS[:-1])+' | '+
            ' | '.join(f"{x[w].get('reward_hacking_detected',0)}/60" for w in ('full_trajectory','final_artifact'))+' |')
    lines+=['','## Revision curves (online W only)','','| Condition | R0 | R1 | R2 | R3 | R3 changed answers |',
            '|---|---:|---:|---:|---:|---:|']
    for c in order:
        x=result['conditions'][c]['revision']
        lines.append('| '+names[c]+' | '+' | '.join(f'{v:.2f}' for v in x['W'])+f" | {x['changed'][2]}/60 |")
    lines+=['','## Paired task differences, RTT minus static','','Task is the independent resampling unit (20 tasks, three paired replicates averaged first). Intervals are descriptive percentile bootstrap, 10,000 draws; selected subset, no multiplicity adjustment.','',
            '| Feedback | Metric | Mean difference | Task-bootstrap 95% | Positive / tie / negative tasks |','|---|---|---:|---|---|']
    for f,metrics in result['paired_task_contrasts'].items():
        for k,x in metrics.items():
            lo,hi=x['task_bootstrap_95']
            lines.append(f"| {f} | {k} | {x['mean']:+.2f} | [{lo:+.2f}, {hi:+.2f}] | {x['positive']} / {x['tie']} / {x['negative']} |")
    lines+=['','## All 20 task means','','| Task | Feedback | Static A | RTT A | ΔA | ΔS | ΔH |','|---|---|---:|---:|---:|---:|---:|']
    for x in sorted(result['task_pairs'],key=lambda x:(x['task_id'],x['feedback'])):
        delta=x['RTT_minus_static']
        lines.append(f"| {x['task_id']} | {x['feedback']} | {x['static']['A']:.2f} | {x['RTT']['A']:.2f} | {delta['A']:+.2f} | {delta['S']:+.2f} | {delta['H']:+.2f} |")
    return '\n'.join(lines)+'\n'


if __name__=='__main__':
    result=analyze()
    (HERE/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'TABLES.md').write_text(tables(result))
    print('Verified 240 assignments; saved analysis.json and TABLES.md. No provider calls.')
