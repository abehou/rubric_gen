"""Source-native matched static simulator comparison, no provider calls."""
import hashlib, importlib.util, json, os, subprocess, sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen'); BUNDLE=Path(__file__).parent
BASE=ROOT/'runs/babel-dev3-rubric-cue-20260908'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    assert os.environ.get('SLURM_JOB_ID')
    out=BASE/'da11-comparison-v1';out.mkdir(exist_ok=False)
    rows=[];sources=[];coverage=[];reference=None;helper_path=None
    arms=[('control','10363145','dev3-evidence-control',ROOT/'runs/babel-dev3-evidence-sidecar-20260908/owners/control-da-11-1',12),('cue','10364143','dev3-rubric-cue',BASE/'owners/cue-da-11-1',6)]
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
        selected=[r for r in data['rows'] if r['condition_id']=='user-simulator-static'];assert len(selected)==6
        rows+=selected;coverage+=data['coverage'];sources.append(dict(arm=arm,job=job,commit=launch['git_commit'],launch=str(receipts[0]),launch_sha256=sha(receipts[0]),native_analysis_sha256=sha(native/'analysis.json')))
    labels=['control/user-simulator-static','cue/user-simulator-static'];assert {r['analysis_condition'] for r in rows}==set(labels)
    for rep in (1,2,3):
        matched=[r for r in rows if r['replicate']==rep];assert len(matched)==4 and all(r['task_id']=='da-11-1' for r in matched)
        assert len({r['initial_submission_sha256'] for r in matched})==len({r['selected_rubric_sha256'] for r in matched})==1
    spec=importlib.util.spec_from_file_location('frozen_analysis',helper_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=helper.aggregate(rows,panel)
    contrast=helper.paired_contrast(rows,labels[1],labels[0],panel)
    payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts={'cue minus control':contrast},coverage=coverage,sources=sources,matched_initial_selected=True,definitions=reference['definitions'],uncertainty=reference['uncertainty'])
    (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
    renderer=ROOT/'investigation/dev3-evidence-sidecar-20260908/report_details.py'
    spec=importlib.util.spec_from_file_location('report_details',renderer);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    lines=['# Bounded rubric-cue simulator: matched da-11-1 comparison','','Three frozen replicates; static policy in both arms. Source-native full coverage validated before selecting the prespecified static comparison. Existing control trace cells are excluded from this simulator-only contrast, not rerun.','','This is one-task development evidence, not full dev3 validation. Inspect generated feedback to confirm actual rubric quotation before interpreting a mechanism.','','## Panel bounds','','| Condition | Full RH | Post RH | Artifact RH | Revision RH | W−S | S−H | H−A | W−A | A |','|---|'+'---:|'*9]
    for label in labels:
        cells=[]
        for key in ['RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision','WS','SH','HA','WA','A']:
            lo,hi=conditions[label+'/matched-panel']['metrics'][key]['identification_bounds'];factor=100 if key.startswith('RH_') else 1
            cells.append(f'{lo*factor:.2f}' if lo==hi else f'{lo*factor:.2f}–{hi*factor:.2f}')
        lines.append('| '+label+' | '+' | '.join(cells)+' |')
    lines+=module.details(payload)
    (ROOT/'docs/reports/2026-09-08/dev3-rubric-cue-da11.md').write_text('\n'.join(lines))
    (out/'receipt.json').write_text(json.dumps(dict(success=True,job=os.environ['SLURM_JOB_ID'],script_sha256=sha(__file__),renderer_sha256=sha(renderer),analysis_sha256=sha(out/'analysis.json'),sources=sources),indent=2)+'\n')
if __name__=='__main__':main()
