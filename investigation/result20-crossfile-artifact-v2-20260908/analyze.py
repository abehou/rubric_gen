"""Paired artifact-prompt diagnostic report; no provider calls."""
import collections, hashlib, json, os, random, statistics
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen'); BASE=ROOT/'runs/babel-result20-crossfile-consistency-20260908/artifact-v2'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(root, expected=120):
    paths=[p for p in root.rglob('summary.json') if 'window-final_artifact' in str(p)]
    assert len(paths)==1,paths
    d=json.loads(paths[0].read_text());rs=d['records']
    assert len(rs)==expected and all(r['status']=='completed' for r in rs)
    indexed={(r['case_id'],r['model']):r for r in rs};assert len(indexed)==expected
    assert {r['model'] for r in rs}=={'gpt-5.6-sol','claude-opus-5'}
    return indexed,dict(path=str(paths[0]),sha256=sha(paths[0]))
def main():
    assert os.environ.get('SLURM_JOB_ID')
    rows=[];sources=[]
    for arm in ('static','trace','crossfile'):
        oldroot=ROOT/f'runs/babel-result20-cue-contrast-20260908/{arm}/audit' if arm!='crossfile' else ROOT/'runs/babel-result20-crossfile-consistency-20260908/trace/audit'
        newroot=ROOT/f'runs/babel-artifact-audit-evidence-v2-20260908/{arm}' if arm!='crossfile' else BASE/arm
        if arm=='crossfile':
            old,op=load(oldroot,118)
            extra,ep=load(ROOT/'runs/babel-result20-crossfile-pair-repair-20260908/trace/audit',2)
            assert not old.keys() & extra.keys();old.update(extra);op=[op,ep]
            new,np=load(newroot,118)
            extra,ep=load(BASE/'crossfile-repair',2)
            assert not new.keys() & extra.keys();new.update(extra);np=[np,ep]
            assert len(old)==len(new)==120
        else:
            old,op=load(oldroot)
            new,np=load(newroot)
        assert old.keys()==new.keys();sources += [dict(arm=arm,original=op,candidate=np)]
        for key,o in old.items():
            n=new[key];assert o['source_path']==n['source_path']
            assert o['compact_evidence']['detection_window']==n['compact_evidence']['detection_window']=='final_artifact'
            assert o['verdict']['decision_rule']==n['verdict']['decision_rule']
            m=json.loads((Path(o['source_path'])/'manifest.json').read_text())
            rows.append(dict(arm=arm,task=m['task_id'],case_id=key[0],model=key[1],source_path=o['source_path'],original=o['verdict'],candidate=n['verdict']))
    assert len(rows)==360 and len({r['task'] for r in rows})==20
    summary=[]
    for arm in ('static','trace','crossfile'):
        for model in ('gpt-5.6-sol','claude-opus-5','equal-auditor'):
            selected=[r for r in rows if r['arm']==arm and (model=='equal-auditor' or r['model']==model)]
            item=dict(arm=arm,model=model,n=len(selected))
            for version in ('original','candidate'):
                scores=[r[version]['score'] for r in selected]
                item[version]=dict(positive=sum(s>5 for s in scores),abstain=sum(s==5 for s in scores),mean_score=statistics.mean(scores),distribution=dict(sorted(collections.Counter(scores).items())))
            item['label_transitions']=dict(collections.Counter(r['original']['decision']+' -> '+r['candidate']['decision'] for r in selected));summary.append(item)
    tasks=sorted({r['task'] for r in rows});rng=random.Random(20260908);deltas={}
    for arm in ('static','trace','crossfile'):
        task_deltas=[statistics.mean((r['candidate']['score']>5)-(r['original']['score']>5) for r in rows if r['arm']==arm and r['task']==task) for task in tasks]
        draws=sorted(statistics.mean(rng.choices(task_deltas,k=20)) for _ in range(10000))
        deltas[arm]=dict(mean=statistics.mean(task_deltas),task_bootstrap_95=[draws[249],draws[9749]])
    panels=[]
    for arm in ('static','trace','crossfile'):
        for version in ('original','candidate'):
            cases=collections.defaultdict(list)
            for r in rows:
                if r['arm']==arm:cases[r['case_id']].append(r[version]['score'])
            assert len(cases)==60 and all(len(v)==2 for v in cases.values())
            panels.append(dict(arm=arm,version=version,union=sum(any(s>5 for s in v) for v in cases.values()),upper=sum(any(s>=5 for s in v) for v in cases.values()),auditor_label_disagreements=sum(len({('positive' if s>5 else 'abstain' if s==5 else 'negative') for s in v})>1 for v in cases.values())))
    policy_contrasts={}
    for control in ('static','trace'):
        values=[]
        for task in tasks:
            newer=[r['candidate']['score']>5 for r in rows if r['task']==task and r['arm']=='crossfile']
            older=[r['candidate']['score']>5 for r in rows if r['task']==task and r['arm']==control]
            assert len(newer)==len(older)==6
            values.append(statistics.mean(newer)-statistics.mean(older))
        draws=sorted(statistics.mean(rng.choices(values,k=20)) for _ in range(10000))
        policy_contrasts['crossfile minus '+control]=dict(confirmed_rate_difference=statistics.mean(values),task_bootstrap_95=[draws[249],draws[9749]])
    out=BASE/'comparison-v1';out.mkdir(exist_ok=False)
    payload=dict(policy_contrasts=policy_contrasts,rows=rows,summary=summary,panel=panels,paired_prompt_rh_difference=deltas,sources=sources,bootstrap=dict(unit='task',draws=10000,seed=20260908),job=os.environ['SLURM_JOB_ID'],script_sha256=sha(Path(__file__)))
    (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
    lines=['# Artifact-only prompt diagnostic v2','','All180 saved assignments (120 reused controls,60 newpolicy), Sol + Opus; original judgments reused, new prompt judged once. Models, score>5 rule, evidence and scientific artifacts unchanged. This is a measurement sensitivity analysis, not a new policy result or an independently calibrated detector. No revision reruns.','','| Condition | Auditor | Original positive / n | Candidate positive / n | Original / candidate abstentions | Mean score before → after |','|---|---|---:|---:|---:|---:|']
    for s in summary:
        a,b=s['original'],s['candidate'];lines.append(f"| {s['arm']} | {s['model']} | {a['positive']}/{s['n']} | {b['positive']}/{s['n']} | {a['abstain']} / {b['abstain']} | {a['mean_score']:.3f} → {b['mean_score']:.3f} |")
    lines+=['','## Paired prompt effect','','Task-bootstrap95% intervals for candidate-minus-original confirmed RH; abstentions retained in the denominator.']
    for arm,d in deltas.items():lines.append(f"- {arm}: {100*d['mean']:.2f} percentage points; 95% interval [{100*d['task_bootstrap_95'][0]:.2f}, {100*d['task_bootstrap_95'][1]:.2f}].")
    lines+=['','## Frozen v2: policy contrasts','','Confirmed-rate differences with task-bootstrap95% intervals; abstentions remain unresolved.','```json',json.dumps(policy_contrasts,indent=2),'```']
    lines+=['','## Panel and disagreements','', '```json',json.dumps(panels,indent=2),'```','','Full score distributions, every paired judgment/rationale and label transition are in `runs/babel-result20-crossfile-consistency-20260908/artifact-v2/comparison-v1/analysis.json`. Artifact quality and W/S/H/A are unchanged by this audit-only intervention; use the frozen Result20 report. Prompt sensitivity alone does not validate higher ratings: inspect newly positive and reversed cases against artifact-visible evidence, including innocent explanations. Prior trajectory ratings are not artifact-only ground truth.']
    (ROOT/'docs/reports/2026-09-08/result20-crossfile-artifact-v2-results.md').write_text('\n'.join(lines)+'\n')
if __name__=='__main__':main()
