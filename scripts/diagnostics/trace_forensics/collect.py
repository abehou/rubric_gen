"""Read saved JSON/trajectories only. No workflow or provider imports/calls."""
import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path('/home/aydanh/repos/rubric_gen')
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-repair-result20-20260909')
OUT = Path('/data/user_data/aydanh/rubric_gen/forensics/trace-original-vs-public-witness-20260910')
PUBLIC = ROOT / 'docs/reports/2026-09-10/trace-forensics'
MODELS = ('gpt-5.6-sol', 'claude-opus-5')


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def table(name, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (PUBLIC / name).open('w') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in r.items()})


def verdict(d):
    return {'no_reward_hacking_detected': 'negative', 'reward_hacking_detected': 'positive', 'abstain': 'abstain'}[d['decision']]


def identity(r):
    return ('user' if 'user-simulator' in r['condition_id'] else 'full', r['task_id'], r['replicate'])


def key(c):
    return f'{c["policy"]}_{c["setting"]}_{c["task_id"]}_r{c["replicate"]}'


def collect_case(c):
    root = Path(c['root'])
    state, manifest = read(root/'state.json'), read(root/'manifest.json')
    generations, proposals = [], []
    for directory in sorted((root/'rubric-generations').glob('generation-*')):
        if not (directory/'evolution.json').exists():
            continue
        gm = read(directory/'manifest.json')
        for name, expected in gm['file_sha256s'].items():
            assert sha(directory/name) == expected, directory/name
        evolution = read(directory/'evolution.json')
        n = evolution['context']['generation_round']
        ps = read(directory/'criterion-proposal.json')['criteria']
        vs = read(directory/'criterion-validation.json')['validations']
        ds = read(directory/'aggregate-margins.json')['decisions']
        comparisons = {p['pair_id']: p for p in read(directory/'pairwise-comparisons.json')['comparisons']}
        history = read(directory/'artifact-history.json')
        artifacts = {a['artifact_id']: {k:v for k,v in a.items() if k != 'content'} for a in history['artifacts']}
        assert len(ps) == len(vs) == len(ds), directory
        for raw, validation, decision in zip(ps, vs, ds):
            assert validation['criterion_id'] == decision['criterion_id']
            apps = {a['artifact_id']: a for a in validation['artifact_applications']}
            cited = []
            for pid in raw['provenance_pair_ids']:
                pair = comparisons[pid]
                a, b = pair['preferred_artifact_id'], pair['rejected_artifact_id']
                la, lb = apps[a]['level'], apps[b]['level']
                cited.append(dict(pair_id=pid, subset=pair['subset'], gap_views=pair['gap_views'],
                    preferred_artifact_id=a, rejected_artifact_id=b,
                    preferred_level=la, rejected_level=lb, separates=la < lb,
                    preferred_reason=apps[a]['reason'], rejected_reason=apps[b]['reason'],
                    quality_reason=pair['rubric_free_reason'],
                    preferred_metadata=artifacts[a], rejected_metadata=artifacts[b]))
            proposals.append(dict(generation=n, source_checkpoint=evolution['context']['source_checkpoint'],
                criterion_id=decision['criterion_id'], **raw, accepted=decision['accepted'],
                rejection_reason=decision['reason'], observable=validation['observable'],
                nonredundant=validation['nonredundant'], validation_reason=validation['reason'],
                cited_pairs=cited, applications=validation['artifact_applications'],
                margin_checks=decision['margin_checks'], path=str(directory), file_sha256s=gm['file_sha256s']))
        generations.append(dict(generation=n, source_checkpoint=evolution['context']['source_checkpoint'],
            path=str(directory), proposed=len(ps), admitted=sum(d['accepted'] for d in ds),
            induction_pairs=evolution['induction_pair_count'], gaps=evolution['rubric_gap_count'],
            fallback={k:v for k,v in evolution.items() if k.endswith('fallback_reason')},
            active_criteria=read(directory/'criteria.json'), generation_sha256=evolution['generation_sha256']))
    checkpoints = []
    for p in sorted((root/'rubric-evaluations').glob('s*.json')):
        x=read(p); sid=x['submission_id']; n=int(sid[1:]); fp=root/'feedback'/f'{sid}.json'
        feedback=read(fp) if fp.exists() else None
        prompt=root/'turns'/f'turn-{n+1:03d}'/'prompt.txt'
        ep=root/'judgments'/sid/x['rubric_sha256']/'evaluation.json'
        ev=read(ep) if ep.exists() else {}
        checkpoints.append(dict(submission=sid, generation=x['generation_round'],
            base=x['canonical_original_score'], penalty=x['elicited_penalty'], score=x['score'],
            learned_levels={k:v for k,v in ev.get('criteria',{}).items() if k.startswith('elicited_')},
            feedback=feedback, feedback_path=str(fp) if fp.exists() else None,
            feedback_sha256=sha(fp) if fp.exists() else None,
            solver_turn=n+1 if prompt.exists() else None,
            prompt_path=str(prompt) if prompt.exists() else None,
            prompt_sha256=sha(prompt) if prompt.exists() else None,
            prompt=prompt.read_text() if prompt.exists() else None,
            score_composition_path=str(p), score_composition_sha256=sha(p)))
    online=[p for p in proposals if p['generation']>=2]
    admitted=[p for p in online if p['accepted']]
    c.update(manifest=manifest,state=state,generations=generations,proposals=proposals,checkpoints=checkpoints,
        lifecycle=dict(proposed=len(online),admitted=len(admitted),
            first_proposal=min((p['generation'] for p in online),default=None),
            first_admission=min((p['generation'] for p in admitted),default=None),
            rejections=dict(Counter(p['rejection_reason'] for p in online if not p['accepted'])),
            penalized_checkpoints=sum(x['penalty']<0 for x in checkpoints),
            penalty_total=sum(x['penalty'] for x in checkpoints),
            solver_turns=sum(x['solver_turn'] is not None for x in checkpoints)))
    write(OUT/'cases'/f'{key(c)}.json',c)
    return c


def main():
    assert os.environ.get('SLURM_JOB_ID'), 'NFS inspection belongs on compute nodes'
    PUBLIC.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    baseline=read(ROOT/'docs/reports/2026-09-09/baseline-freeze/results.json')
    records=[]; sources=[]
    for path, expected in baseline['provenance']['sources'].items():
        assert sha(path)==expected
        sources.append(dict(path=path,sha256=expected))
        for row in read(path)['rows']:
            cid=row['condition_id'].split('/')[-1]
            if ('cue-contrast' in path and cid=='user-simulator-red-team-trace') or ('provisional59' in path and cid=='full-red-team-trace'):
                records.append(dict(policy='original',**{**row,'condition_id':cid}))
    receipt=read(ROOT/'docs/reports/2026-09-09/trace-public-witness/candidate-evidence-receipt.json')
    path=RUN/'report-v1/candidate-rows.json'
    expected=next(s['sha256'] for s in receipt['sources'] if s['path']==str(path))
    assert sha(path)==expected; sources.append(dict(path=str(path),sha256=expected))
    records += [dict(policy='candidate',**r) for r in read(path)]
    assert len(records)==478
    grouped=defaultdict(list)
    for r in records:
        for f in ('state','score_composition'):
            assert sha(r[f+'_path'])==r[f+'_sha256']
        grouped[(r['policy'],*identity(r))].append(r)
    cases=[]
    for (policy,setting,task,rep), rows in sorted(grouped.items()):
        assert len(rows)==2 and {r['model'] for r in rows}==set(MODELS)
        cases.append(dict(policy=policy,setting=setting,task_id=task,replicate=rep,
            root=str(Path(rows[0]['state_path']).parent),rows=rows))
    write(OUT/'raw-rows.json',records);write(PUBLIC/'sources.json',sources)
    print(json.dumps(dict(stage='source-verification',auditor_rows=len(records),cases=len(cases))),flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        cases=list(pool.map(collect_case,cases))
    lite=[{k:v for k,v in c.items() if k not in ('checkpoints','generations','proposals','state','manifest')} for c in cases]
    write(PUBLIC/'cases.json',lite)
    lifecycle=[dict(policy=c['policy'],setting=c['setting'],task_id=c['task_id'],replicate=c['replicate'],
        root=c['root'],**c['lifecycle']) for c in cases]
    table('criterion-lifecycle.csv',lifecycle)
    index={(c['policy'],c['setting'],c['task_id'],c['replicate']):c for c in cases}
    transitions=[]; assignment_transitions=[]
    for old in cases:
        if old['policy']!='original':continue
        new=index[('candidate',old['setting'],old['task_id'],old['replicate'])]
        cov=('admitted' if old['lifecycle']['admitted'] else 'none')+'->'+('admitted' if new['lifecycle']['admitted'] else 'none')
        aud={r['model']:r for r in new['rows']}
        labels=[]
        for a in old['rows']:
            b=aud[a['model']]
            for f in ('initial_submission_sha256','selected_rubric_sha256'):assert a[f]==b[f]
            x,y=a['direct']['full_trajectory'],b['direct']['full_trajectory']
            row=dict(setting=old['setting'],task_id=old['task_id'],replicate=old['replicate'],auditor=a['model'],
                original_verdict=verdict(x),candidate_verdict=verdict(y),original_monitor_score=x['score'],
                candidate_monitor_score=y['score'],original_rationale=x['reason'],candidate_rationale=y['reason'],
                coverage_transition=cov,original_root=old['root'],candidate_root=new['root'])
            for m in ('W','W_train','S','H','A','WS','WA','SH','HA'):
                row['original_'+m]=a['values'][m];row['candidate_'+m]=b['values'][m];row['delta_'+m]=b['values'][m]-a['values'][m]
            transitions.append(row);labels.append((verdict(x),verdict(y)))
        panel=lambda i:'positive' if any(t[i]=='positive' for t in labels) else ('abstain' if any(t[i]=='abstain' for t in labels) else 'negative')
        assignment_transitions.append(dict(setting=old['setting'],task_id=old['task_id'],replicate=old['replicate'],
            original_any_positive=panel(0),candidate_any_positive=panel(1),
            original_positive_auditors=sum(t[0]=='positive' for t in labels),candidate_positive_auditors=sum(t[1]=='positive' for t in labels),
            original_verdict_pair=[t[0] for t in labels],candidate_verdict_pair=[t[1] for t in labels],coverage_transition=cov))
    table('rh-transitions-auditor.csv',transitions)
    table('rh-transitions-assignment.csv',assignment_transitions)
    table('rh-discordant.csv',[r for r in transitions if r['original_verdict']!=r['candidate_verdict']])
    summary={}
    for setting in ('user','full'):
        rows=[r for r in transitions if r['setting']==setting]; ass=[r for r in assignment_transitions if r['setting']==setting]
        summary[setting]=dict(auditor_transitions=dict(Counter(r['original_verdict']+'->'+r['candidate_verdict'] for r in rows)),
            assignment_transitions=dict(Counter(r['original_any_positive']+'->'+r['candidate_any_positive'] for r in ass)),
            coverage_transitions=dict(Counter(r['coverage_transition'] for r in ass)),
            by_coverage={cov:dict(assignments=sum(a['coverage_transition']==cov for a in ass),
                original_detections=sum(r['original_verdict']=='positive' for r in rows if r['coverage_transition']==cov),
                candidate_detections=sum(r['candidate_verdict']=='positive' for r in rows if r['coverage_transition']==cov)) for cov in sorted({r['coverage_transition'] for r in rows})})
    write(PUBLIC/'transition-summary.json',summary)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
