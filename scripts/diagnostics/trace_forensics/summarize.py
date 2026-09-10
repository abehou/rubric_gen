"""Deterministic descriptive tables from saved case extracts, no new judgments."""
from collections import Counter,defaultdict
from statistics import mean,median
from collect import OUT,PUBLIC,read,write,table,key


def distribution(xs):
    xs=[x for x in xs if x is not None]
    return dict(n=len(xs),mean=mean(xs) if xs else None,median=median(xs) if xs else None,histogram=dict(sorted(Counter(xs).items())))


cases=[read(p) for p in sorted((OUT/'cases').glob('*.json'))]
groups=defaultdict(list)
for c in cases:groups[c['policy'],c['setting']].append(c)
summary=[]; proposals=[]; pairrows=[]; timings=[]
for (policy,setting),cs in groups.items():
    ps=[p for c in cs for p in c['proposals'] if p['generation']>=2]
    summary.append(dict(policy=policy,setting=setting,assignments=len(cs),any_proposal=sum(c['lifecycle']['proposed']>0 for c in cs),any_admission=sum(c['lifecycle']['admitted']>0 for c in cs),proposed=len(ps),admitted=sum(p['accepted'] for p in ps),rejections=dict(Counter(p['rejection_reason'] for p in ps if not p['accepted'])),penalized_checkpoints=sum(c['lifecycle']['penalized_checkpoints'] for c in cs),penalty_total=sum(c['lifecycle']['penalty_total'] for c in cs),solver_turns=sum(c['lifecycle']['solver_turns'] for c in cs),first_proposal=distribution([c['lifecycle']['first_proposal'] for c in cs]),first_admission=distribution([c['lifecycle']['first_admission'] for c in cs]),proposal_generations=distribution([p['generation'] for p in ps]),admission_generations=distribution([p['generation'] for p in ps if p['accepted']])))
    for c in cs:
        for p in c['proposals']:
            if p['generation']<2:continue
            pairs=p['cited_pairs']; sep=sum(x['separates'] for x in pairs); ties=sum(x['preferred_level']==x['rejected_level'] for x in pairs); rev=sum(x['preferred_level']>x['rejected_level'] for x in pairs)
            pattern=('mixed_supported_unsupported' if 0<sep<len(pairs) else 'all_supported' if sep==len(pairs) else 'ties_only' if ties==len(pairs) else 'reversed_present_no_support')
            base=dict(policy=policy,setting=setting,task_id=c['task_id'],replicate=c['replicate'],generation=p['generation'],criterion_id=p['criterion_id'])
            proposals.append(dict(**base,title=p['title'],requirement=p['requirement'],accepted=p['accepted'],rejection_reason=p['rejection_reason'],replaces=p['replaces'],citations=len(pairs),supported=sep,tied=ties,reversed=rev,observed_support_pattern=pattern,path=p['path'],file_sha256s=p['file_sha256s']))
            for x in pairs:pairrows.append(dict(**base,**x))
        for x in c['checkpoints']:
            timings.append(dict(policy=policy,setting=setting,task_id=c['task_id'],replicate=c['replicate'],generation=x['generation'],submission=x['submission'],solver_turn=x['solver_turn'],active_criteria=len(x['learned_levels']),violated_criteria=sum(v['points']<0 for v in x['learned_levels'].values()),penalty=x['penalty'],feedback=x['feedback'],prompt_path=x['prompt_path'],prompt_sha256=x['prompt_sha256']))
table('proposals.csv',proposals);table('cited-pair-applications.csv',pairrows);table('checkpoint-timing.csv',timings);write(PUBLIC/'lifecycle-summary.json',summary)
support=[]
for (policy,setting),cs in groups.items():
    ps=[x for x in proposals if x['policy']==policy and x['setting']==setting and x['rejection_reason']=='criterion_support_failed']
    support.append(dict(policy=policy,setting=setting,support_rejections=len(ps),own_citations_fail=sum(x['supported']<x['citations'] for x in ps),patterns=dict(Counter(x['observed_support_pattern'] for x in ps)),replacement_criteria=sum(bool(x['replaces']) for x in ps)))
write(PUBLIC/'support-observed-summary.json',support)
lookup={(c['policy'],c['setting'],c['task_id'],c['replicate']):c for c in cases}; gaps=[]
for c in cases:
    if c['policy']!='candidate':continue
    o=lookup.get(('original',c['setting'],c['task_id'],c['replicate']))
    if not o:continue
    coverage=('admitted' if o['lifecycle']['admitted'] else 'none')+'->'+('admitted' if c['lifecycle']['admitted'] else 'none')
    row=dict(setting=c['setting'],task_id=c['task_id'],replicate=c['replicate'],coverage=coverage,original_admitted=o['lifecycle']['admitted'],candidate_admitted=c['lifecycle']['admitted'])
    for metric in ['W','S','H','A','WS','WA','SH','HA']:
        row['original_'+metric]=mean(r['values'][metric] for r in o['rows']);row['candidate_'+metric]=mean(r['values'][metric] for r in c['rows']);row['delta_'+metric]=row['candidate_'+metric]-row['original_'+metric]
    gaps.append(row)
table('gap-contributions.csv',gaps)
strata=[]
for setting in ['user','full']:
    for coverage in sorted({g['coverage'] for g in gaps}):
        rr=[g for g in gaps if g['setting']==setting and g['coverage']==coverage]
        strata.append(dict(setting=setting,coverage=coverage,n=len(rr),**{m:mean(r[m] for r in rr) for m in ['delta_W','delta_S','delta_A','delta_WS','delta_WA','delta_SH','delta_HA']},improve_WS=sum(r['delta_WS']<0 for r in rr),improve_WA=sum(r['delta_WA']<0 for r in rr)))
table('gap-coverage-strata.csv',strata)
print('LIFECYCLE',summary);print('SUPPORT',support);print('GAP STRATA',strata)
for metric in ['WS','WA']:
    print('TOP USER',metric,[{k:g[k] for k in ['task_id','replicate','coverage','delta_W','delta_S','delta_A','delta_WS','delta_WA']} for g in sorted([g for g in gaps if g['setting']=='user'],key=lambda g:g['delta_'+metric])[:8]])
