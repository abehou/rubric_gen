"""Complete source-native static comparison; no provider calls."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-result20-cue-score-first-trace-20260909'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 assert os.environ.get('SLURM_JOB_ID')
 out=BASE/'comparison-v1';out.mkdir(exist_ok=False);rows=[];sources=[];coverage=[];reference=None
 for label,job,run,checkout,expected in [('static','10368806','babel-result20-cue-score-first-20260909','result20-cue-score-first',120),('trace','10368826','babel-result20-cue-score-first-trace-20260909','result20-cue-score-first',120)]:
  receipt=next((ROOT/'runs'/run/f'owners/{label}-results20').glob(f'{job}-*/launch.json'));launch=json.loads(receipt.read_text());result=json.loads(receipt.with_name('result.json').read_text());assert result['source_unchanged']
  assert result['success']
  assert all(sha(p)==h for p,h in launch['source_hashes'].items())
  code=ROOT/'runs/babel-code'/checkout;helper=code/'investigation/babel-overnight-20260907/analyze_babel.py';native=out/f'{label}-{job}-native'
  cmd=[sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(native),'--label',label]
  with (out/f'{label}-{job}.log').open('x') as stream:subprocess.run(cmd,cwd=code,env=dict(os.environ,PYTHONPATH=str(code/'src')),stdout=stream,stderr=subprocess.STDOUT,check=True)
  data=json.loads((native/'analysis.json').read_text());assert len(data['rows'])==expected
  if reference is None:reference=data;helper_hash=sha(helper)
  assert data['definitions']==reference['definitions'] and data['uncertainty']==reference['uncertainty'] and sha(helper)==helper_hash
  rows+=data['rows'];coverage+=data['coverage'];sources.append(dict(label=label,job=job,launch=str(receipt),launch_sha256=sha(receipt),commit=launch['git_commit'],native_sha256=sha(native/'analysis.json')))
 assert len({(r['analysis_condition'],r['task_id'],r['replicate'],r['model']) for r in rows})==240
 tasks={r['task_id'] for r in rows};assert len(tasks)==20
 for task in tasks:
  for rep in (1,2,3):
   rs=[r for r in rows if r['task_id']==task and r['replicate']==rep];assert len(rs)==4
   assert len({r['initial_submission_sha256'] for r in rs})==len({r['selected_rubric_sha256'] for r in rs})==1
 spec=importlib.util.spec_from_file_location('native_analysis',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=module.aggregate(rows,panel)
 contrast=module.paired_contrast(rows,'trace/user-simulator-red-team-trace','static/user-simulator-static',panel)
 payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts={'trace minus static':contrast},coverage=coverage,sources=sources,definitions=reference['definitions'],uncertainty=reference['uncertainty'])
 exposure_path=ROOT/'investigation/babel-overnight-20260907/feedback_exposure.py'
 spec=importlib.util.spec_from_file_location('feedback_exposure',exposure_path);exposure_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(exposure_module)
 exposure=exposure_module.exposure(rows)
 from score_exposure import summarize
 disclosure=summarize(rows)
 disclosure['source_sha256']=sha(Path(__file__).with_name('score_exposure.py'))
 (out/'score-disclosure-screen.json').write_text(json.dumps(disclosure,indent=2)+'\n')
 exposure['source_sha256']=sha(exposure_path)
 (out/'feedback-exposure.json').write_text(json.dumps(exposure,indent=2)+'\n')
 payload['feedback_exposure_summary']=exposure['conditions']
 (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
 renderer=ROOT/'investigation/dev3-evidence-sidecar-20260908/report_details.py';spec=importlib.util.spec_from_file_location('details',renderer);render=importlib.util.module_from_spec(spec);spec.loader.exec_module(render)
 intro=['# First-concern earned-score disclosure: matched static versus trace Result20','','Twenty canonical tasks × three replicates per condition. All120 assignments/240auditor rows validated; seeds and selected rubrics matched. Primary detectors, models and thresholds unchanged. Earlier fidelity replays and bounded-score cohorts are excluded from this comparison. This is developmental Result20, not untouched confirmation.','','Inspect actual feedback exposure alongside RH and quality. Both arms use identical score-disclosing simulator wording; trace adds the existing dynamic policy. Inspect policy admission and actual feedback exposure. Report null/adverse results.','']
 (ROOT/'docs/reports/2026-09-09/result20-cue-score-first-trace.md').write_text('\n'.join(intro+render.details(payload)+['','## Feedback exposure and revision behavior','','Descriptive counts; not a causal mediation analysis. Full source-linked details are in comparison-v1/feedback-exposure.json.','','```json',json.dumps(exposure['conditions'],indent=2),'```','','## Score disclosure screen','',disclosure['caveat'],'','```json',json.dumps(disclosure['conditions'],indent=2),'```'])+'\n')
 (out/'receipt.json').write_text(json.dumps(dict(success=True,job_id=os.environ['SLURM_JOB_ID'],analysis_sha256=sha(out/'analysis.json'),script_sha256=sha(__file__)))+'\n')
if __name__=='__main__':main()
