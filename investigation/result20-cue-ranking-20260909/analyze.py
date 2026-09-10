"""Reuse frozen cue analyses and analyze only the new trace arm; no providers."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent;BASE=ROOT/'runs/babel-result20-cue-ranking-20260909';OLD=ROOT/'runs/babel-result20-cue-contrast-20260908/comparison-v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def module(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
assert os.environ.get('SLURM_JOB_ID')
owner=BASE/'owners/trace-results20';receipts=list(owner.glob('10371501-*/launch.json'));assert len(receipts)==1
launch=json.loads(receipts[0].read_text());completion=json.loads(receipts[0].with_name('result.json').read_text());assert completion['success'] and completion['source_unchanged']
for name,h in launch['source_hashes'].items():assert sha(Path(name))==h
reference=json.loads((OLD/'analysis.json').read_text());oldreceipt=json.loads((OLD/'receipt.json').read_text());assert sha(OLD/'analysis.json')==oldreceipt['analysis_sha256']
code=ROOT/'runs/babel-code/result20-cue-ranking';helper=code/'investigation/babel-overnight-20260907/analyze_babel.py';out=BASE/'comparison-v1';out.mkdir(exist_ok=False)
cmd=[sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(out/'ranking-native'),'--label','ranking']
with (out/'ranking-native.log').open('x') as f:subprocess.run(cmd,cwd=code,env=dict(os.environ,PYTHONPATH=str(code/'src')),stdout=f,stderr=subprocess.STDOUT,check=True)
fresh=json.loads((out/'ranking-native/analysis.json').read_text());assert len(fresh['rows'])==120
assert fresh['definitions']==reference['definitions'] and fresh['uncertainty']==reference['uncertainty']
rows=reference['rows']+fresh['rows'];assert len(rows)==360
for task in {r['task_id'] for r in rows}:
 for rep in [1,2,3]:
  matched=[r for r in rows if r['task_id']==task and r['replicate']==rep];assert len(matched)==6
  assert len({r['initial_submission_sha256'] for r in matched})==len({r['selected_rubric_sha256'] for r in matched})==1
m=module('ranking_analysis',helper);panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=m.aggregate(rows,panel)
labels=['static/user-simulator-static','trace/user-simulator-red-team-trace','ranking/user-simulator-red-team-trace']
contrasts={f'ranking minus {label.split("/")[0]}':m.paired_contrast(rows,labels[2],label,panel) for label in labels[:2]}
payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts=contrasts,coverage=reference['coverage']+fresh['coverage'],sources=reference['sources']+[dict(arm='ranking',job='10371501',commit=launch['git_commit'],launch=str(receipts[0]),launch_sha256=sha(receipts[0]),native_analysis_sha256=sha(out/'ranking-native/analysis.json'))],definitions=reference['definitions'],uncertainty=reference['uncertainty'],frozen_reference_sha256=sha(OLD/'analysis.json'))
(out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
render=module('ranking_details',ROOT/'investigation/dev3-evidence-sidecar-20260908/report_details.py')
intro=['# Rubric-cue ranking-preservation Result20 comparison','','Frozen static and original trace analyses are reused; only ranking trace is new.20tasks×3replicates per arm, two frozen auditors. This is development evidence, not untouched confirmation.','','Only online non-strict positive-margin shrinkage changes admission. Offline starting criteria and cue simulator are frozen. Primary success criteria: non-worsening W−S and W−A versus static; meaningful trajectory-RH reduction with paired uncertainty; holistic-quality noninferiority. Final-artifact RH remains under the original uncalibrated auditor and is secondary. Inspect exposure before attributing mechanism; report all null/adverse outcomes.','']
(ROOT/'docs/reports/2026-09-09/result20-cue-ranking.md').write_text('\n'.join(intro+render.details(payload))+'\n')
(out/'receipt.json').write_text(json.dumps(dict(success=True,job_id=os.environ['SLURM_JOB_ID'],script_sha256=sha(Path(__file__)),analysis_sha256=sha(out/'analysis.json')),indent=2)+'\n')
