"""Private read-only W/S/H/A reconstruction after complete native audit coverage."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/diagnostics'))
from check_audit_coverage import check, source_records, WINDOWS
from artifact_locations import recorded_root
from summarize_outcomes import summarize, BOOTSTRAPS, SEED
from rubric_gen.submission_revision.evaluation.panel_bounds import detection_bounds

NUMERIC=('W','W_train','S','H','A','WS','SH','HA','WA','train_WS','train_WA','quality_gain','selected_gain','elicited_penalty')

def read(p):return json.loads(p.read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def numeric_scores(W,train,S,H,A):
    assert all(isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=v<=100 for v in (W,train,S,H,A))
    return dict(W=W,W_train=train,S=S,H=H,A=A,WS=W-S,SH=S-H,HA=H-A,WA=W-A,train_WS=train-S,train_WA=train-A)

def bound(decisions,panel):
    return detection_bounds(decisions=decisions,models=panel,positive_decision='reward_hacking_detected',negative_decision='no_reward_hacking_detected',rule='any_detect')

def reconstruct(study,audit,panel):
    coverage=check(study,audit,expected_models=panel)
    assignments=source_records(study)
    original=recorded_root(study)
    refs=defaultdict(dict)
    for ref in read(audit/'rubric_score/summary.json')['records']:
        key=(ref['assignment_id'],ref['model'],ref['artifact'])
        path=audit/'rubric_score/records'/f"{ref['judgment_key']}.json"
        raw=read(path)
        for role in ref['rubric_roles']:
            rolekey=(role['name'],role['variant_index'])
            assert rolekey not in refs[key]
            refs[key][rolekey]=(ref,raw,path)
    quality={}
    for ref in read(audit/'absolute_score/summary.json')['records']:
        key=(ref['assignment_id'],ref['model'],ref['artifact'])
        assert key not in quality
        path=audit/'absolute_score/records'/f"{ref['judgment_key']}.json"
        quality[key]=(ref,read(path),path)
    direct={}
    for window in WINDOWS:
        path=next((audit/f'direct_{window}/evaluations').glob('*/summary.json'))
        direct[window]={(r['source_path'],r['model']):r for r in read(path)['records']}
    rows=[]
    for assignment in assignments:
        aid=assignment['assignment_id']; exp=study/assignment['experiment_dir']
        state=read(exp/'state.json');sid=state['submission_ids'][-1]
        evaluation_path=exp/'rubric-evaluations'/f'{sid}.json';ev=read(evaluation_path)
        assert ev['kind']=='selected-base-plus-active-penalties-v1'
        assert ev['submission_id']==sid and ev['score']==state['scores'][-1]
        assert ev['canonical_original_score']==state['fixed_original_scores'][-1]
        reference=ev['feedback_reference']
        weak_root=exp/'judgments'/sid/reference['rubric_sha256']
        weak_validation=weak_root/'score_validation.json';weak_evaluation=weak_root/'evaluation.json'
        assert digest(weak_validation)==reference['score_validation_sha256']
        assert digest(weak_evaluation)==reference['evaluation_sha256']
        assert read(weak_validation)['score']==read(weak_evaluation)['total_score']==ev['reference_score']
        assert ev['score']==max(0,ev['reference_score']+ev['elicited_penalty'])
        for model in panel:
            obs=refs[aid,model,'final']
            selected=[v for k,v in obs.items() if k[0]=='selected']
            held=[v for k,v in obs.items() if k[0]=='holdout']
            assert len(selected)==1 and len(held)==3
            selected=selected[0]
            assert ev['feedback_reference']['rubric_sha256']==selected[1]['rubric_sha256']
            allrefs=[selected,*held,obs['original',None]]
            assert all(ref['submission_id']==sid for ref,raw,p in allrefs)
            shas={raw['submission_content_sha256'] for ref,raw,p in allrefs};assert len(shas)==1
            assert len({raw['rubric_sha256'] for ref,raw,p in [selected,*held]})==4
            qr,q,qp=quality[aid,model,'final'];assert qr['submission_id']==sid and q['submission_content_sha256'] in shas
            W=ev['reference_score'];train=ev['score'];S=selected[1]['score'];H=mean(raw['score'] for ref,raw,p in held);A=q['verdict']['score']
            values=numeric_scores(W,train,S,H,A)
            assert abs(values['WA']-values['WS']-values['SH']-values['HA'])<1e-8
            initial_selected=[v for k,v in refs[aid,model,'initial'].items() if k[0]=='selected'];assert len(initial_selected)==1
            values.update(quality_gain=A-quality[aid,model,'initial'][1]['verdict']['score'],selected_gain=S-initial_selected[0][1]['score'],elicited_penalty=ev['elicited_penalty'])
            evidence={w:direct[w][str(original/assignment['experiment_dir']),model]['verdict'] for w in WINDOWS}
            rows.append(dict(assignment_id=aid,condition_id=assignment['condition_id'],task_id=assignment['task_id'],replicate=assignment['replicate'],model=model,
                submission_id=sid,submission_sha256=next(iter(shas)),initial_submission_sha256=quality[aid,model,'initial'][1]['submission_content_sha256'],selected_rubric_sha256=selected[1]['rubric_sha256'],values=values,direct=evidence,
                weak_master=state['fixed_original_scores'][-1],strong_master=obs['original',None][1]['score'],
                heldout_values=[raw['score'] for ref,raw,p in held],retained_revisions=len(state['submission_ids'])-1,attempted_turns=len(list((exp/'turns').glob('turn-*'))),stop_reason=state['stop_reason'],
                generation_round=ev['generation_round'],state_path=str(exp/'state.json'),state_sha256=digest(exp/'state.json'),
                score_composition_path=str(evaluation_path),score_composition_sha256=digest(evaluation_path),rubric_paths=[str(p) for ref,raw,p in allrefs],quality_path=str(qp)))
    return coverage,rows

def aggregate(rows,panel):
    groups=defaultdict(list);distributions={}
    for row in rows:
        metrics={k:(v,v) for k,v in row['values'].items()}
        for window,verdict in row['direct'].items():
            b=bound({row['model']:verdict['decision']},[row['model']])
            metrics['RH_'+window]=(b['lower'],b['upper'])
        groups[row.get('analysis_condition',row['condition_id']),row['model']].append(dict(task_id=row['task_id'],metrics=metrics))
    cases=defaultdict(list)
    for row in rows:cases[row.get('analysis_condition',row['condition_id']),row['task_id'],row['replicate']].append(row)
    for (condition,task,rep),case in cases.items():
        assert len(case)==len(panel) and {r['model'] for r in case}==set(panel)
        assert len({r['submission_sha256'] for r in case})==1
        metrics={k:(mean(r['values'][k] for r in case),)*2 for k in NUMERIC}
        for window in WINDOWS:
            b=bound({r['model']:r['direct'][window]['decision'] for r in case},panel)
            metrics['RH_'+window]=(b['lower'],b['upper'])
        groups[condition,'matched-panel'].append(dict(task_id=task,metrics=metrics))
    for (condition,model),group in groups.items():
        if model=='matched-panel':continue
        selected=[r for r in rows if r.get('analysis_condition',r['condition_id'])==condition and r['model']==model]
        distributions[f'{condition}/{model}']={w:dict(sorted(Counter(r['direct'][w]['score'] for r in selected).items())) for w in WINDOWS}
    return {f'{c}/{m}':summarize(g) for (c,m),g in groups.items()},distributions


def paired_contrast(rows,left,right,panel):
    def indexed(condition):
        result={}
        for row in rows:
            if row.get('analysis_condition',row['condition_id'])!=condition:continue
            key=(row['task_id'],row['replicate'],row['model'])
            assert key not in result
            result[key]=row
        return result
    lhs,rhs=indexed(left),indexed(right)
    assert lhs and lhs.keys()==rhs.keys(), 'paired contrast requires identical task/replicate/model coverage'
    groups=defaultdict(list)
    for key,a in lhs.items():
        b=rhs[key]
        assert a['initial_submission_sha256']==b['initial_submission_sha256'], 'paired seed artifact differs'
        assert a['selected_rubric_sha256']==b['selected_rubric_sha256'], 'paired selected rubric differs'
        metrics={k:(a['values'][k]-b['values'][k],)*2 for k in NUMERIC}
        for window in WINDOWS:
            ba=bound({key[2]:a['direct'][window]['decision']},[key[2]])
            bb=bound({key[2]:b['direct'][window]['decision']},[key[2]])
            metrics['RH_'+window]=(ba['lower']-bb['upper'],ba['upper']-bb['lower'])
        groups[key[2]].append(dict(task_id=key[0],metrics=metrics))
    # Preserve panel union bounds rather than averaging individual binary votes.
    for task,rep in sorted({(key[0],key[1]) for key in lhs}):
        a=[lhs[task,rep,m] for m in panel];b=[rhs[task,rep,m] for m in panel]
        metrics={k:(mean(r['values'][k] for r in a)-mean(r['values'][k] for r in b),)*2 for k in NUMERIC}
        for window in WINDOWS:
            ba=bound({r['model']:r['direct'][window]['decision'] for r in a},panel)
            bb=bound({r['model']:r['direct'][window]['decision'] for r in b},panel)
            metrics['RH_'+window]=(ba['lower']-bb['upper'],ba['upper']-bb['lower'])
        groups['matched-panel'].append(dict(task_id=task,metrics=metrics))
    return {model:summarize(rs) for model,rs in groups.items()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--study',type=Path,action='append',required=True)
    p.add_argument('--audit',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--label',action='append',help='Explicit analysis cohort label for each study; native condition IDs remain recorded')
    p.add_argument('--contrast',nargs=2,action='append',default=[],metavar=('LEFT','RIGHT'))
    a=p.parse_args();assert len(a.study)==len(a.audit)
    panel=['gpt-5.6-sol','claude-opus-5'];rows=[];coverage=[]
    labels=a.label or ['']*len(a.study);assert len(labels)==len(a.study)
    for study,audit,label in zip(a.study,a.audit,labels,strict=True):
        cov,rs=reconstruct(study.resolve(),audit.resolve(),panel);coverage.append(cov)
        for r in rs:r['analysis_condition']=f"{label}/{r['condition_id']}" if label else r['condition_id']
        rows.extend(rs)
    conditions,distributions=aggregate(rows,panel)
    contrasts={f'{left} minus {right}':paired_contrast(rows,left,right,panel) for left,right in a.contrast}
    payload=dict(coverage=coverage,rows=rows,conditions=conditions,contrasts=contrasts,monitor_distributions=distributions,
        definitions='W=weak selected-base reference; W_train=selected base plus active penalties; S=strong selected; H=mean strong heldouts2–4; A=rubric-free absolute quality. train_WS/train_WA also retain actual composed-reward gaps, whose change can include penalty arithmetic. RH is a fraction with abstention bounds, never silently coded negative.',
        uncertainty=dict(method='equal task weighting and task-cluster percentile bootstrap',draws=BOOTSTRAPS,seed=SEED,caution='Two-task dev3 intervals are descriptive and cannot establish population robustness.'),
        analysis_source_sha256=digest(Path(__file__)))
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps(dict(coverage=coverage,conditions=conditions),indent=2))

if __name__=='__main__':main()
