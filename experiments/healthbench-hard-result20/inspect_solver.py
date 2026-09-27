"""Provider-free inventory of the completed solver cohort; not an outcome audit."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/healthbench-hard-challenge20-local-20260926'
STUDY = RUN / 'studies/healthbench-hard-factorial-r3-01eb8a5a9277'

def read(p):
    return json.loads(p.read_text())

def inspect():
    rows = []
    for rec in read(STUDY / 'study.json')['records']:
        root = STUDY / rec['experiment_dir']
        state = read(root / 'state.json')
        events = [json.loads(s) for s in (root / 'events.jsonl').read_text().splitlines()]
        snapshots = {}
        for sid in state['submission_ids']:
            p = root / 'submissions' / sid / 'workspace/answer.txt'
            text = p.read_text()
            ev = read(root / 'rubric-evaluations' / (sid + '.json'))
            snapshots[sid] = {'answer_path':str(p.relative_to(ROOT)), 'answer':text,
                'words':len(text.split()), 'W':ev['reference_score'],
                'canonical':ev['canonical_original_score'], 'penalty':ev['elicited_penalty']}
        # Map real revision turns, carrying forward only when no new snapshot was saved.
        rounds = []
        sid = state['submission_ids'][0]
        for turn in range(4):
            found = [e for e in events if e['event']=='submission_judged' and e['turn']==turn]
            if found:
                sid = found[-1]['submission_id']
            rounds.append(dict(snapshots[sid], sid=sid))
        accepted, generations = [], []
        for p in sorted((root/'rubric-generations').glob('*/evolution.json')):
            e=read(p)
            ids=e.get('accepted_candidate_ids',[])
            criteria=read(p.parent/'criteria.json')
            for c in criteria:
                if c['criterion_id'] in ids:
                    accepted.append(dict(c, generation=p.parent.name))
            generations.append({'generation':p.parent.name,'accepted':ids,
                'gaps':e.get('rubric_gap_count'), 'induction_attempts':e.get('induction_attempt_count'),
                'fallbacks':{k:v for k,v in e.items() if 'fallback_reason' in k and v}})
        rows.append({**{k:rec[k] for k in ['task_id','replicate','condition_id','status','attempt_count']},
            'root':str(root.relative_to(ROOT)), 'stop':state['stop_reason'],
            'rounds':rounds,'accepted':accepted,'generations':generations,
            'changed':[rounds[i]['answer']!=rounds[i-1]['answer'] for i in range(1,4)]})
    grouped=defaultdict(list)
    for row in rows: grouped[row['condition_id']].append(row)
    groups={}
    for c,rr in sorted(grouped.items()):
        groups[c]={'n':len(rr), 'W':[mean(r['rounds'][i]['W'] for r in rr) for i in range(4)],
            'canonical':[mean(r['rounds'][i]['canonical'] for r in rr) for i in range(4)],
            'words':[mean(r['rounds'][i]['words'] for r in rr) for i in range(4)],
            'perfect':[sum(r['rounds'][i]['W']>=99.999 for r in rr) for i in range(4)],
            'changed':[sum(r['changed'][i] for r in rr) for i in range(3)],
            'W_steps':[dict(Counter('up' if r['rounds'][i]['W']>r['rounds'][i-1]['W'] else 'down' if r['rounds'][i]['W']<r['rounds'][i-1]['W'] else 'flat' for r in rr)) for i in range(1,4)],
            'accepted':sum(len(r['accepted']) for r in rr),
            'assignments_with_accepted':sum(bool(r['accepted']) for r in rr),
            'accepted_by_generation':dict(Counter(a['generation'] for r in rr for a in r['accepted'])),
            'fallbacks':sum(bool(g['fallbacks']) for r in rr for g in r['generations'])}
    tasks=[]
    for t in sorted({r['task_id'] for r in rows}):
        rr=[r for r in rows if r['task_id']==t]
        tasks.append({'task':t,'final_W':{c:round(mean(r['rounds'][-1]['W'] for r in rr if r['condition_id']==c),2) for c in grouped},
            'initial_words':round(mean(r['rounds'][0]['words'] for r in rr)),
            'final_words':{c:round(mean(r['rounds'][-1]['words'] for r in rr if r['condition_id']==c)) for c in grouped}})
    return {'status':dict(Counter(r['status'] for r in rows)), 'stops':dict(Counter(r['stop'] for r in rows)),
        'groups':groups,'tasks':tasks,'rows':rows}

if __name__=='__main__':
    result=inspect()
    Path(__file__).with_name('solver-inspection.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
