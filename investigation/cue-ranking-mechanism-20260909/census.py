"""Saved-artifact census; no providers or outcome exclusions."""
import collections, hashlib, json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
base=root/'runs/babel-result20-cue-ranking-20260909/comparison-v1'
p=base/'analysis.json'; rows=json.loads(p.read_text())['rows']
by=collections.defaultdict(dict)
for r in rows:
    arm=r['analysis_condition'].split('/')[0]
    key=(r['task_id'],r['replicate'],r['model'])
    assert arm not in by[key]
    by[key][arm]=r
assert len(by)==120 and all(set(v)=={'static','trace','ranking'} for v in by.values())
ex={}
for arm,file in [('trace','original_trace'),('ranking','ranking_trace')]:
    d=json.loads((base/f'joint-and-exposure-10371561/{file}-exposure.json').read_text())
    ex[arm]={a['assignment']:a for a in d['assignments']}
def positive(r):return r['direct']['full_trajectory']['decision']=='reward_hacking_detected'
out=[]; transitions=collections.Counter(); strata=collections.defaultdict(lambda:collections.Counter())
for key,arms in sorted(by.items()):
    a,b=arms['trace'],arms['ranking']; ea=ex['trace'][a['assignment_id']]['counts']; eb=ex['ranking'][b['assignment_id']]['counts']
    change=f'{int(positive(a))}->{int(positive(b))}'
    transitions[change]+=1
    group='no_online_admission' if not eb['accepted'] else ('online_admitted_any_penalty' if eb['negative_penalty_checkpoints'] else 'online_admitted_no_penalty')
    strata[group]['rows']+=1;strata[group]['original_positive']+=positive(a);strata[group]['ranking_positive']+=positive(b)
    out.append({'task':key[0],'replicate':key[1],'auditor':key[2],'transition':change,'ranking_exposure_group':group,'original_online_accepted':ea['accepted'],'ranking_online_accepted':eb['accepted'],'ranking_any_penalty_checkpoints':eb['negative_penalty_checkpoints'],'arms':{arm:{'positive':positive(r),'decision':r['direct']['full_trajectory']['decision'],'reason':r['direct']['full_trajectory'].get('reason'),'values':r['values'],'state_path':r['state_path'],'retained_revisions':r['retained_revisions'],'stop_reason':r['stop_reason']} for arm,r in arms.items()}})
report=root/'docs/reports/2026-09-09/cue-ranking-mechanism-census.json'
report.write_text(json.dumps({'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'transitions':dict(transitions),'exposure_strata':dict(strata),'rows':out,'limitation':'Auditor rows are paired repeated observations, not independent cases. Exposure groups are post-treatment descriptions, not causal estimates. A negative-to-positive transition may originate from an abstention; exact decisions are retained.'},indent=2)+'\n')
md=['# Ranking-policy mechanism census','', 'Complete frozen comparison: 60 matched assignments × two auditors. No provider calls or exclusions.','', '## Full-trajectory transitions: original trace → ranking trace','', '| Confirmed RH transition | Auditor rows |','|---|---:|']
md += [f'| {k} | {v} |' for k,v in sorted(transitions.items())]
md += ['', '## Actual online exposure in the ranking arm','', '| Exposure | Rows | Original RH-positive | Ranking RH-positive |','|---|---:|---:|---:|']
md += [f"| {k} | {v['rows']} | {v['original_positive']} | {v['ranking_positive']} |" for k,v in strata.items()]
md += ['', 'These are descriptive post-treatment strata. Penalty-checkpoint counts can include retained offline criteria; they do not identify which online criterion was penalized. Admission and assessment do not prove simulator delivery or causal prevention. Case-level auditor reasons, scores, stop behavior, and source state paths are preserved in the adjacent JSON. Next inspect timing and actual feedback for every new-positive case before proposing another policy.']
report.with_suffix('.md').write_text('\n'.join(md)+'\n')
print('\n'.join(md))
