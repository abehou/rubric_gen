"""Combine reusable frozen arms with the single missing cue full-feedback arm."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
R=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent
CODE=R/'runs/babel-code/result20-cue-full-counterpart'
BASE=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-full-trace-20260909')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
assert os.environ.get('SLURM_JOB_ID')
receipts=sorted((BASE/'owners/trace-results20').glob('*/launch.json'))
assert receipts
successful=[p for p in receipts if p.with_name('result.json').exists() and read(p.with_name('result.json')).get('success')]
assert successful
launchpath=successful[-1];launch=read(launchpath)
assert all(sha(p)==h for p,h in launch['source_hashes'].items())
out=BASE/'matched-report-v1';out.mkdir(exist_ok=False)
helperpath=CODE/'investigation/babel-overnight-20260907/analyze_babel.py'
cmd=[sys.executable,str(helperpath),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(out/'full-trace-native'),'--label','cue-full-trace']
with (out/'native.log').open('x') as log:subprocess.run(cmd,cwd=CODE,env=dict(os.environ,PYTHONPATH=str(CODE/'src')),stdout=log,stderr=subprocess.STDOUT,check=True)
new=read(out/'full-trace-native/analysis.json');assert len(new['rows'])==120
oldpath=R/'runs/babel-result20-current-20260908/report-v2/analysis.json';cuepath=R/'runs/babel-result20-cue-contrast-20260908/comparison-v1/analysis.json'
old=read(oldpath);cue=read(cuepath)
assert new['definitions']==old['definitions']==cue['definitions']
assert new['uncertainty']==old['uncertainty']==cue['uncertainty']
rows=[r for r in old['rows'] if r['condition_id']=='full-static']+cue['rows']+new['rows']
assert len(rows)==480
for r in rows:
 assert sha(r['state_path'])==r['state_sha256']
 assert sha(r['score_composition_path'])==r['score_composition_sha256']
keys={(r['condition_id'],r['task_id'],r['replicate'],r['model']) for r in rows};assert len(keys)==480
for task in {r['task_id'] for r in rows}:
 for rep in [1,2,3]:
  group=[r for r in rows if r['task_id']==task and r['replicate']==rep];assert len(group)==8
  assert len({r['initial_submission_sha256'] for r in group})==len({r['selected_rubric_sha256'] for r in group})==1
spec=importlib.util.spec_from_file_location('helper',helperpath);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=helper.aggregate(rows,panel)
labels={r['condition_id']:r['analysis_condition'] for r in rows}
contrasts={}
for l,r in [('full-red-team-trace','full-static'),('user-simulator-red-team-trace','user-simulator-static'),('full-static','user-simulator-static'),('full-red-team-trace','user-simulator-red-team-trace')]:
 contrasts[f'{l} minus {r}']=helper.paired_contrast(rows,labels[l],labels[r],panel)
payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts=contrasts,definitions=new['definitions'],uncertainty=new['uncertainty'],sources={str(p):sha(p) for p in [oldpath,cuepath,launchpath,helperpath,R/'docs/reports/2026-09-09/cue-full-compatibility.json']},reuse='Earlier full-static reused unchanged; earlier full-trace excluded because policy inputs differ; cue user arms reused unchanged.')
(out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
lines=['# Matched rubric-cue Result20: full feedback and user simulator','','240 assignments: three archived arms reused, one missing full-trace arm generated. Original labels and provenance preserved. RH is equal-weight confirmed Sol/Opus rate, not panel union.','','| Condition | Trajectory RH | Artifact RH (uncalibrated) | W | W_train | S | H | A | W−S | S−H | H−A | W−A |','|---|'+'---:|'*11]
for condition in ['full-static','full-red-team-trace','user-simulator-static','user-simulator-red-team-trace']:
 rs=[r for r in rows if r['condition_id']==condition];assert len(rs)==120
 rates=[sum(r['direct'][w]['decision']=='reward_hacking_detected' for r in rs)/len(rs)*100 for w in ['full_trajectory','final_artifact']]
 vals=[sum(r['values'][k] for r in rs)/len(rs) for k in ['W','W_train','S','H','A','WS','SH','HA','WA']]
 lines.append('| '+condition+' | '+' | '.join(f'{v:.2f}' for v in rates+vals)+' |')
lines+=['','Task-paired contrasts, abstention bounds, per-auditor scores, monitor distributions and provenance are in '+str(out/'analysis.json')+'. Artifact measurement has not completed independent human calibration; no calibrated mitigation claim.','',payload['reuse']]
(R/'docs/reports/2026-09-09/result20-cue-four-condition.md').write_text('\n'.join(lines)+'\n')
(out/'receipt.json').write_text(json.dumps(dict(success=True,job=os.environ['SLURM_JOB_ID'],analysis_sha256=sha(out/'analysis.json'),script_sha256=sha(__file__)),indent=2)+'\n')
print('Complete matched four-condition cue report:',out)
