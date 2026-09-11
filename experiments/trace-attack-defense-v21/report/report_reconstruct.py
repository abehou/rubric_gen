"""Read-only native final W/S/H/A reconstruction, adapted without outcome changes.

Source: investigation/babel-overnight-20260907/analyze_babel.py.
This report-only adapter is not imported by execution or any evaluator.
"""
from collections import defaultdict
from statistics import mean
from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/diagnostics'))
from check_audit_coverage import check, source_records, WINDOWS
from artifact_locations import recorded_root

def read(p):return json.loads(Path(p).read_text())
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def numeric_scores(W,train,S,H,A):
    assert all(isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=v<=100 for v in (W,train,S,H,A))
    return dict(W=W,W_train=train,S=S,H=H,A=A,WS=W-S,SH=S-H,HA=H-A,WA=W-A,train_WS=train-S,train_WA=train-A)

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
