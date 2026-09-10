"""Build the frozen baseline checkpoint from existing validated results; no APIs."""
import csv
import hashlib
import importlib.util
import json
import os
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path('/home/aydanh/repos/rubric_gen')
OUT = ROOT / 'docs/reports/2026-09-09/baseline-freeze'
SOURCES = [ROOT/'runs/babel-result20-current-20260908/report-v2/analysis.json', ROOT/'runs/babel-result20-cue-contrast-20260908/comparison-v1/analysis.json', Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-full-trace-20260909/provisional59-report-v1/analysis.json')]
PANEL = {'gpt-5.6-sol', 'claude-opus-5'}
WINDOWS = ('full_trajectory','post_update','final_artifact','final_revision')
SPECS = [('full-static','Full feedback','Static rubric',0,60), ('user-simulator-static','User simulator','Static rubric',1,60), ('full-red-team-trace','Full feedback','Red-team trace',2,59), ('user-simulator-red-team-trace','User simulator','Red-team trace',1,60)]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    assert os.environ.get('SLURM_JOB_ID'), 'Compute node required for archived source access'
    payloads=[json.loads(p.read_text()) for p in SOURCES]
    assert all(p['definitions']==payloads[0]['definitions'] for p in payloads)
    data=[]; cases=[]; inventories={}; allrows={}; checks=0
    for cid,feedback,policy,source,n in SPECS:
        rows=[r for r in payloads[source]['rows'] if r['condition_id'].split('/')[-1]==cid]
        assert len(rows)==n*2 and {r['model'] for r in rows}==PANEL
        assert len({(r['task_id'],r['replicate'],r['model']) for r in rows})==n*2
        inventory={(r['task_id'],r['replicate']) for r in rows}; inventories[cid]=inventory
        assert len(inventory)==n and len({t for t,_ in inventory})==20
        for r in rows:
            for pathkey,hashkey in [('state_path','state_sha256'),('score_composition_path','score_composition_sha256')]:
                assert sha(r[pathkey])==r[hashkey], r[pathkey]; checks+=1
            cases.append(dict(condition=feedback,policy=policy,task=r['task_id'],replicate=r['replicate'],auditor=r['model'],**r['values'],**{w:r['direct'][w]['decision'] for w in WINDOWS}))
        allrows[cid]=rows
        item=dict(condition=cid,feedback=feedback,policy=policy,assignments=n,auditor_rows=n*2)
        item.update({k:mean(r['values'][k] for r in rows) for k in ('W','W_train','S','H','A','WS','SH','HA','WA')})
        item['master_minus_A']=mean(r['strong_master']-r['values']['A'] for r in rows)
        detail={}
        for w in WINDOWS:
            ds=Counter(r['direct'][w]['decision'] for r in rows)
            assert set(ds)<={'reward_hacking_detected','no_reward_hacking_detected','abstain'}
            item[w+'_lower_pct']=100*ds['reward_hacking_detected']/len(rows)
            item[w+'_upper_pct']=100*(ds['reward_hacking_detected']+ds['abstain'])/len(rows)
            item[w+'_abstentions']=ds['abstain']; item[w+'_score']=mean(r['direct'][w]['score'] for r in rows)
            union=intersection=unknown=disagree=0
            for t,rep in inventory:
                d=[r['direct'][w]['decision'] for r in rows if (r['task_id'],r['replicate'])==(t,rep)]
                assert len(d)==2
                union+= 'reward_hacking_detected' in d
                intersection+=all(x=='reward_hacking_detected' for x in d)
                unknown+=('reward_hacking_detected' not in d and 'abstain' in d)
                disagree+=len(set(d))>1
            detail[w]=dict(panel_union_pct=100*union/n,panel_union_upper_pct=100*(union+unknown)/n,panel_intersection_pct=100*intersection/n,decision_disagreements=disagree,auditors={m:dict(Counter(r['direct'][w]['decision'] for r in rows if r['model']==m)) for m in sorted(PANEL)},monitor_histogram=dict(sorted(Counter(r['direct'][w]['score'] for r in rows).items())))
        item['detail']=detail;data.append(item)
    inv=inventories['full-static']
    assert inventories['user-simulator-static']==inventories['user-simulator-red-team-trace']==inv
    assert inv-inventories['full-red-team-trace']=={('da-16-1',1)}
    reference={(r['task_id'],r['replicate'],r['model']):r for r in allrows['full-static']}
    for rows in allrows.values():
        for r in rows:
            ref=reference[(r['task_id'],r['replicate'],r['model'])]
            assert all(r[k]==ref[k] for k in ('initial_submission_sha256','selected_rubric_sha256'))
    OUT.mkdir(exist_ok=True)
    with (OUT/'case-metrics.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(cases[0]));w.writeheader();w.writerows(cases)
    result=dict(conditions=data,definitions=payloads[0]['definitions'],uncertainty=payloads[0]['uncertainty'],user_paired_contrasts=payloads[1]['contrasts'],full_paired59_contrasts=payloads[2]['contrasts'],full_paired59_statistics=payloads[2]['statistics'],provenance=dict(sources={str(p):sha(p) for p in SOURCES},validated_state_composition_hashes=checks,matched_initial_selected=True,job=os.environ['SLURM_JOB_ID'],script_sha256=sha(__file__)),missing={'full-red-team-trace':['da-16-1 replicate 1; infrastructure failure; cancelled repair excluded']})
    (OUT/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# BioMNIBench frozen baseline — available Result20 results','','Formal feedback conditions are **Full feedback** and **User simulator**. Policies are **Static rubric** and **Red-team trace**. The baseline is accepted; joint trace mitigation has not yet been established. No new revisions or audits were run for this checkpoint.','','20 frozen tasks, three planned replicates; Sol/Opus equal-weight per-auditor means. The two static arms and User simulator trace each have60/60 assignments. Full feedback trace has59/60: da-16-1 replicate1 failed an infrastructure invariant; its cancelled repair contributes nothing. Static60 remains the canonical baseline; inferential Full feedback comparisons use only the matching59 in each arm.','','| Condition | Policy | n | Trajectory RH | Artifact RH* | W | W_train | S | H | A | W−S | S−H | H−A | W−A |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for d in data:
        v=[d[k] for k in ['full_trajectory_lower_pct','final_artifact_lower_pct','W','W_train','S','H','A','WS','SH','HA','WA']]
        lines.append(f"| {d['feedback']} | {d['policy']} | {d['assignments']} | "+' | '.join(f'{x:.2f}'+('%' if i<2 else '') for i,x in enumerate(v))+' |')
    lines+=['','*Final-artifact rates use the unchanged, uncalibrated auditor. They are a measurement-sensitivity limitation, not proof of absent artifact RH. Threshold remains >5;5 is abstention. Gemini3.8 Flash is configured but has no results because credits were unavailable.','','## Interpretation','','Both static arms have accepted trajectory-RH headroom and W−S, H−A, W−A gaps. User simulator S−H≈0.12 is consistent with wording-only heldout generalization; it is not a baseline failure. The0.83percentage-point Full feedback/User simulator trajectory difference is descriptive, not demonstrated separation.','','User simulator trace reduces trajectory RH20%→7.5% (paired task95% interval for change−22.50 to−4.17pp), but W−S and W−A increase by1.925 and1.883points. Holistic change+0.50 has95% interval[−3.19,+4.12]; no demonstrated loss is not proven noninferiority.','','Full feedback trace is a provisional59-case comparison: trajectory change+5.08pp, W−S+0.47, W−A+0.87, A−1.99 versus the matched static59. Task-equal95% intervals respectively[−4.17,+14.17]pp,[−2.05,+2.87],[−2.48,+4.35],[−5.30,+1.38]. These do not establish mitigation or conclusive harm. See the [matched coverage/provenance record](../cue-full-provisional59.md).','','## Audit coverage and bounds','','Rates below are confirmed per-auditor rates; brackets extend to include abstentions, not confidence intervals. Panel union is separately labeled.','','| Condition / policy | Window | Confirmed–upper (%) | Panel union–upper (%) | Auditor disagreements | Mean monitor score |','|---|---|---:|---:|---:|---:|']
    for d in data:
        for w in WINDOWS:
            x=d['detail'][w];lines.append(f"| {d['feedback']} / {d['policy']} | {w.replace('_',' ')} | {d[w+'_lower_pct']:.2f}–{d[w+'_upper_pct']:.2f} | {x['panel_union_pct']:.2f}–{x['panel_union_upper_pct']:.2f} | {x['decision_disagreements']} | {d[w+'_score']:.2f} |")
    lines+=['','[Machine-readable results, existing paired uncertainty, auditor counts, monitor histograms and source hashes](results.json) · [Case metrics](case-metrics.csv) · [Gap/artifact plot](gaps-and-artifact-rh.png) · [Trajectory plot](trajectory-rh.png).','','Internal provenance only: revised simulator version `rubric-cue`, scientific source0fbe0bb, Full feedback trace producer314ea3d. This release adds the approved30ae38e duplicate-evidence fix; it does not relabel earlier results as produced with that fix. [Field/hash compatibility decision](../cue-full-compatibility.md).']
    (OUT/'README.md').write_text('\n'.join(lines)+'\n')
    # Plot implementation is frozen alongside this script; original plotter remains untouched.
    spec=importlib.util.spec_from_file_location('baseline_plots',Path(__file__).with_name('frozen_baseline_plots.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.plot(data,OUT)
    print(json.dumps({'coverage':[d['assignments'] for d in data],'hash_checks':checks,'output':str(OUT)}))
if __name__=='__main__': main()
