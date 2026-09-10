"""Reuse frozen cue analyses and analyze only the new trace arm; no providers."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent;BASE=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909');OLD=ROOT/'runs/babel-result20-cue-contrast-20260908/comparison-v1'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def module(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
assert os.environ.get('SLURM_JOB_ID')
RECOVERY=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-pair-recovery-20260909')
original_receipt=BASE/'audit-owners/10374539'
assert json.loads((original_receipt/'result.json').read_text())['success']
replacement_receipt=next((RECOVERY/'owners/trace-results20').glob('10374492-*/launch.json'))
replacement=json.loads(replacement_receipt.read_text())
assert json.loads(replacement_receipt.with_name('result.json').read_text())['success']
reference=json.loads((OLD/'analysis.json').read_text());oldreceipt=json.loads((OLD/'receipt.json').read_text());assert sha(OLD/'analysis.json')==oldreceipt['analysis_sha256']
out=BASE/'comparison-recovered-v3';out.mkdir(exist_ok=False)
original_launch=json.loads(next((BASE/'owners/trace-results20').glob('10373129-*/launch.json')).read_text())
fresh_parts=[];sources=[]
for label,launch,code,expected in [('original59',original_launch,ROOT/'runs/babel-code/result20-cue-original-audit',118),('replacement1',replacement,ROOT/'runs/babel-code/result20-cue-active-violations',2)]:
 helper=B/'analyze_native.py'
 cmd=[sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(out/label),'--label','active']
 with (out/f'{label}.log').open('x') as f:subprocess.run(cmd,cwd=code,env=dict(os.environ,PYTHONPATH=str(code/'src')),stdout=f,stderr=subprocess.STDOUT,check=True)
 part=json.loads((out/label/'analysis.json').read_text());assert len(part['rows'])==expected
 assert part['definitions']==reference['definitions'] and part['uncertainty']==reference['uncertainty']
 fresh_parts.append(part)
 sources.append(dict(part=label,commit=launch['git_commit'],source_job=launch['job_id'],native_analysis_sha256=sha(out/label/'analysis.json')))
fresh=dict(rows=[r for part in fresh_parts for r in part['rows']],coverage=[c for part in fresh_parts for c in part['coverage']],definitions=reference['definitions'],uncertainty=reference['uncertainty'])
assert len(fresh['rows'])==120
assert len({(r['task_id'],r['replicate'],r['model']) for r in fresh['rows']})==120
code=ROOT/'runs/babel-code/result20-cue-original-audit';helper=B/'analyze_native.py'
rows=reference['rows']+fresh['rows'];assert len(rows)==360
for task in {r['task_id'] for r in rows}:
 for rep in [1,2,3]:
  matched=[r for r in rows if r['task_id']==task and r['replicate']==rep];assert len(matched)==6
  assert len({r['initial_submission_sha256'] for r in matched})==len({r['selected_rubric_sha256'] for r in matched})==1
m=module('active_analysis',helper);panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=m.aggregate(rows,panel)
labels=['static/user-simulator-static','trace/user-simulator-red-team-trace','active/user-simulator-red-team-trace']
contrasts={f'active minus {label.split("/")[0]}':m.paired_contrast(rows,labels[2],label,panel) for label in labels[:2]}
payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts=contrasts,coverage=reference['coverage']+fresh['coverage'],sources=reference['sources']+sources,definitions=reference['definitions'],uncertainty=reference['uncertainty'],frozen_reference_sha256=sha(OLD/'analysis.json'))
(out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
render=module('active_details',ROOT/'investigation/dev3-evidence-sidecar-20260908/report_details.py')
intro=['# Rubric-cue active-violation delivery Result20 comparison','','Frozen static and original trace analyses are reused; only active-violation trace is new.20tasks×3replicates per arm, two frozen auditors. This is development evidence, not untouched confirmation.','','One infrastructure-invalid assignment was regenerated at repaired source30ae38e; the other59retain producingc507d40. All60task/replicate keys are required, with separate source receipts.', 'Only solver delivery of currently violated elicited requirements changes. The original admission rule is preserved. Offline starting criteria and cue simulator are frozen. Primary success criteria: non-worsening W−S and W−A versus static; meaningful trajectory-RH reduction with paired uncertainty; holistic-quality noninferiority. Final-artifact RH remains under the original uncalibrated auditor and is secondary. Inspect exposure before attributing mechanism; report all null/adverse outcomes.','']
(ROOT/'docs/reports/2026-09-09/result20-cue-active-violations.md').write_text('\n'.join(intro+render.details(payload))+'\n')
(out/'receipt.json').write_text(json.dumps(dict(success=True,job_id=os.environ['SLURM_JOB_ID'],script_sha256=sha(Path(__file__)),analysis_sha256=sha(out/'analysis.json')),indent=2)+'\n')
