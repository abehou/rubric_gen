"""Source-native matched static simulator comparison, no provider calls."""
import hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen'); BUNDLE=Path(__file__).parent
BASE=ROOT/'runs/babel-result20-cue-contrast-20260908'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    assert os.environ.get('SLURM_JOB_ID')
    out=BASE/'comparison-v1';out.mkdir(exist_ok=False)
    rows=[];sources=[];coverage=[];reference=None;helper_path=None
    arms=[('static','10365215','result20-cue-contrast',BASE/'owners/static-results20',120),('trace','10364364','result20-cue-contrast',BASE/'owners/trace-results20',120)]
    for arm,job,checkout,owner,expected in arms:
        receipts=list(owner.glob(f'{job}-*/launch.json'));assert len(receipts)==1
        launch=json.loads(receipts[0].read_text());result=json.loads(receipts[0].with_name('result.json').read_text());assert result['success'] and result['source_unchanged']
        for n,h in launch['source_hashes'].items():assert sha(n)==h,n
        code=ROOT/'runs/babel-code'/checkout;helper=code/'investigation/babel-overnight-20260907/analyze_babel.py'
        if helper_path is None:helper_path=helper
        assert sha(helper)==sha(helper_path)
        native=out/f'{arm}-native';env=dict(os.environ,PYTHONPATH=str(code/'src'))
        cmd=[sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(native),'--label',arm]
        with (out/f'{arm}-native.log').open('x') as stream:subprocess.run(cmd,cwd=code,env=env,stdout=stream,stderr=subprocess.STDOUT,check=True)
        data=json.loads((native/'analysis.json').read_text());assert len(data['rows'])==expected
        if reference is None:reference=data
        assert data['definitions']==reference['definitions'] and data['uncertainty']==reference['uncertainty']
        selected=data['rows'];assert len(selected)==120
        rows+=selected;coverage+=data['coverage'];sources.append(dict(arm=arm,job=job,commit=launch['git_commit'],launch=str(receipts[0]),launch_sha256=sha(receipts[0]),native_analysis_sha256=sha(native/'analysis.json'),attempt_receipts=[dict(path=str(p),sha256=sha(p)) for p in sorted(owner.glob('*/launch.json'))],archived_invalid_attempts=[dict(path=str(p),sha256=sha(p)) for p in sorted((BASE/'invalid-attempts').glob('*/manifest.json'))] if arm=='static' else []))
    labels=['static/user-simulator-static','trace/user-simulator-red-team-trace'];assert {r['analysis_condition'] for r in rows}==set(labels)
    tasks={r['task_id'] for r in rows};assert len(tasks)==20 and len(rows)==240
    for task in tasks:
        for rep in (1,2,3):
            matched=[r for r in rows if r['replicate']==rep and r['task_id']==task];assert len(matched)==4
            assert len({r['initial_submission_sha256'] for r in matched})==len({r['selected_rubric_sha256'] for r in matched})==1
    spec=importlib.util.spec_from_file_location('frozen_analysis',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=helper.aggregate(rows,panel)
    contrast=helper.paired_contrast(rows,labels[1],labels[0],panel)
    payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts={'trace minus static':contrast},coverage=coverage,sources=sources,matched_initial_selected=True,definitions=reference['definitions'],uncertainty=reference['uncertainty'])
    (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
    renderer=ROOT/'investigation/dev3-evidence-sidecar-20260908/report_details.py'
    spec=importlib.util.spec_from_file_location('report_details',renderer);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    lines=['# Result20: rubric-cue static versus revised trace','','Twenty canonical tasks × three frozen replicates × two user-simulator conditions;120 assignments and240 auditor rows. Same simulator and source in both arms; source-native full audit coverage validated. Historical Result20 artifacts are unchanged.','','Primary targets are equal-weight final-artifact and full-trajectory RH. Inspect actual rubric quotation and criterion exposure before attributing a mechanism; this is a cumulative revised-policy test. Report null or adverse findings.','','## Panel bounds','','| Condition | Full RH | Post RH | Artifact RH | Revision RH | W−S | S−H | H−A | W−A | A |','|---|'+'---:|'*9]
    for label in labels:
        cells=[]
        for key in ['RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision','WS','SH','HA','WA','A']:
            lo,hi=conditions[label+'/matched-panel']['metrics'][key]['identification_bounds'];factor=100 if key.startswith('RH_') else 1
            cells.append(f'{lo*factor:.2f}' if lo==hi else f'{lo*factor:.2f}–{hi*factor:.2f}')
        lines.append('| '+label+' | '+' | '.join(cells)+' |')
    lines += [line.replace('A single-task comparison cannot estimate across-task stability. Paired uncertainty in analysis.json does not overcome that limitation.', 'Paired task-bootstrap uncertainty is recorded in analysis.json. These20 tasks have been used in development; this is not an untouched held-out confirmation.') for line in module.details(payload)]
    (ROOT/'docs/reports/2026-09-08/result20-cue-contrast.md').write_text('\n'.join(lines))
    (out/'receipt.json').write_text(json.dumps(dict(success=True,job=os.environ['SLURM_JOB_ID'],script_sha256=sha(__file__),renderer_sha256=sha(renderer),analysis_sha256=sha(out/'analysis.json'),sources=sources),indent=2)+'\n')
if __name__=='__main__':main()
