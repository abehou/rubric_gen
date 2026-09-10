"""Native-validate each producing source, then combine distinctly labeled arms."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
BASE=ROOT/'runs/babel-dev3-evidence-contrast-20260908'
OLD_BASE=ROOT/'runs/babel-dev3-evidence-sidecar-20260908'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    assert os.environ.get('SLURM_JOB_ID')
    out=BASE/'da11-comparison-v1';out.mkdir(exist_ok=False)
    sources=[];rows=[];coverage=[];reference=None;helper_path=None
    for arm,job,checkout in [('control','10363145','dev3-evidence-control'),('evidence','10363146','dev3-evidence-sidecar'),('contrast','10364255','dev3-evidence-contrast')]:
        owner=(BASE if arm=='contrast' else OLD_BASE)/f'owners/{arm}-da-11-1';found=list(owner.glob(f'{job}-*/launch.json'));assert len(found)==1
        launch=json.loads(found[0].read_text());result=json.loads(found[0].with_name('result.json').read_text());assert result['success'] and result['source_unchanged']
        for n,h in launch['source_hashes'].items():assert sha(n)==h,n
        code=ROOT/'runs/babel-code'/checkout;helper=code/'investigation/babel-overnight-20260907/analyze_babel.py'
        if helper_path is None:helper_path=helper
        assert sha(helper)==sha(helper_path)
        native=out/f'{arm}-native';env=dict(os.environ,PYTHONPATH=str(code/'src'))
        cmd=[sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(native),'--label',arm]
        with (out/f'{arm}-native.log').open('x') as f:subprocess.run(cmd,cwd=code,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
        data=json.loads((native/'analysis.json').read_text());assert len(data['rows'])==(12 if arm=='control' else 6)
        assert all(r['task_id']=='da-11-1' for r in data['rows'])
        if reference is None:reference=data
        assert data['definitions']==reference['definitions'] and data['uncertainty']==reference['uncertainty']
        rows+=data['rows'];coverage+=data['coverage'];sources.append(dict(arm=arm,job=job,commit=launch['git_commit'],launch=str(found[0]),launch_sha256=sha(found[0]),analysis_sha256=sha(native/'analysis.json')))
    labels=['control/user-simulator-static','control/user-simulator-red-team-trace','evidence/user-simulator-red-team-trace','contrast/user-simulator-red-team-trace'];assert {r['analysis_condition'] for r in rows}==set(labels)
    for rep in [1,2,3]:
        rs=[r for r in rows if r['replicate']==rep]
        assert len(rs)==8 and len({r['initial_submission_sha256'] for r in rs})==len({r['selected_rubric_sha256'] for r in rs})==1
    initial_training_rubrics={}
    for row in rows:
        if row['condition_id']=='user-simulator-red-team-trace':
            g=Path(row['state_path']).parent/'rubric-generations/generation-0001'
            initial_training_rubrics[f"{row['analysis_condition']}/rep-{row['replicate']}"]={'rubric_sha256':sha(g/'rubric.txt'),'criteria_sha256':sha(g/'criteria.json'),'criterion_count':len(json.loads((g/'criteria.json').read_text()))}
    matched_initial_training_rubrics=all(initial_training_rubrics[f'control/user-simulator-red-team-trace/rep-{rep}']==initial_training_rubrics[f'evidence/user-simulator-red-team-trace/rep-{rep}']==initial_training_rubrics[f'contrast/user-simulator-red-team-trace/rep-{rep}'] for rep in [1,2,3])
    spec=importlib.util.spec_from_file_location('frozen_analysis',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=helper.aggregate(rows,panel)
    contrasts={f'{left} minus {right}':helper.paired_contrast(rows,left,right,panel) for left,right in [(labels[0],labels[3]),(labels[1],labels[3]),(labels[2],labels[3])]}
    payload=dict(rows=rows,coverage=coverage,conditions=conditions,contrasts=contrasts,monitor_distributions=distributions,definitions=reference['definitions'],uncertainty=reference['uncertainty'],sources=sources,matched_seed_selected_hashes=True,initial_training_rubrics=initial_training_rubrics,matched_initial_training_rubrics=matched_initial_training_rubrics,analysis_source_sha256=sha(helper_path))
    (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
    text=['# Contrast-specific proposer: da-11-1 development comparison','', 'One canonical task × three frozen replicates. This is a tuning/runtime gate, not full dev3 or Result20 evidence. All native source-specific audit checks passed; Sol and Opus only.','', '| Condition | Full RH panel bounds | Post-update RH | Final-artifact RH | Final-revision RH | W | W_train | S | H | A |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for label in labels:
        m=conditions[label+'/matched-panel']['metrics'];values=[]
        for k in ['RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision','W','W_train','S','H','A']:
            lo,hi=m[k]['identification_bounds'];scale=100 if k.startswith('RH_') else 1;values.append(f'{lo*scale:.2f}' if lo==hi else f'{lo*scale:.2f}–{hi*scale:.2f}')
        text.append('| '+label+' | '+' | '.join(values)+' |')
    text+=['',f'The initial training rubrics match across trace arms: {matched_initial_training_rubrics}. Their hashes and criterion counts are recorded in analysis.json.','','RH values are percentages; bounds reflect abstentions. Complete auditor-specific metrics, gaps, scores, revision behavior and paired uncertainty are in analysis.json. Inspect actual criterion exposure before interpreting any difference as mitigation.','']
    sys.path.insert(0,str(ROOT/'investigation/dev3-evidence-sidecar-20260908'))
    from report_details import details
    text += details(payload)
    (ROOT/'docs/reports/2026-09-08/dev3-contrast-da11.md').write_text('\n'.join(text))
    (out/'receipt.json').write_text(json.dumps(dict(success=True,job=os.environ['SLURM_JOB_ID'],script_sha256=sha(__file__),report_details_sha256=sha(ROOT/'investigation/dev3-evidence-sidecar-20260908/report_details.py'),analysis_sha256=sha(out/'analysis.json'),sources=sources),indent=2)+'\n')
if __name__=='__main__':main()
