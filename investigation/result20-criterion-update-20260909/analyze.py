"""Complete source-native static comparison; no provider calls."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-result20-criterion-update-20260909'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def comparison_details(payload, render):
 lines = [line for line in render.details(payload)
          if not line.startswith('A single-task comparison cannot estimate')]
 lines += ['', '## Paired differences and uncertainty', '',
           'All 20 tasks are retained. RH differences are percentage points. Identification bounds reflect abstentions; bootstrap intervals reflect task-level sampling uncertainty. Matched-panel RH uses panel-union semantics, not the equal-auditor rates above.', '',
           '| Contrast | Auditor / panel | Metric | Difference bounds | Task bootstrap 95% interval |',
           '|---|---|---|---:|---:|']
 for contrast, panels in payload['contrasts'].items():
  for panel, data in panels.items():
   for metric, stats in data['metrics'].items():
    factor = 100 if metric.startswith('RH_') else 1
    bounds = ' to '.join(f'{v * factor:.2f}' for v in stats['identification_bounds'])
    interval = ' to '.join(f'{v * factor:.2f}' for v in stats['task_bootstrap_95_interval'])
    lines.append(f'| {contrast} | {panel} | {metric} | {bounds} | {interval} |')
 return lines

def main():
 assert os.environ.get('SLURM_JOB_ID')
 out=BASE/'comparison-v1';out.mkdir(exist_ok=False);rows=[];sources=[];coverage=[];reference=None
 for label,job,run,checkout,expected in [('static','10368806','babel-result20-cue-score-first-20260909','result20-cue-score-first',120),('trace','10368826','babel-result20-cue-score-first-trace-20260909','result20-cue-score-first',120),('update','10370740','babel-result20-criterion-update-20260909','result20-criterion-update',120)]:
  receipt=next((ROOT/'runs'/run/f'owners/{"static" if label == "static" else "audit-recovery-trace" if label == "update" else "trace"}-results20').glob(f'{job}-*/launch.json'));launch=json.loads(receipt.read_text());result=json.loads(receipt.with_name('result.json').read_text());assert result['source_unchanged']
  assert result['success']
  assert all(sha(p)==h for p,h in launch['source_hashes'].items())
  code=ROOT/'runs/babel-code'/checkout;helper=code/'investigation/babel-overnight-20260907/analyze_babel.py';native=out/f'{label}-{job}-native'
  cmd=[sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(native),'--label',label]
  with (out/f'{label}-{job}.log').open('x') as stream:subprocess.run(cmd,cwd=code,env=dict(os.environ,PYTHONPATH=str(code/'src')),stdout=stream,stderr=subprocess.STDOUT,check=True)
  data=json.loads((native/'analysis.json').read_text());assert len(data['rows'])==expected
  if reference is None:reference=data;helper_hash=sha(helper)
  assert data['definitions']==reference['definitions'] and data['uncertainty']==reference['uncertainty'] and sha(helper)==helper_hash
  rows+=data['rows'];coverage+=data['coverage'];sources.append(dict(label=label,job=job,launch=str(receipt),launch_sha256=sha(receipt),commit=launch['git_commit'],native_sha256=sha(native/'analysis.json')))
 assert len({(r['analysis_condition'],r['task_id'],r['replicate'],r['model']) for r in rows})==360
 tasks={r['task_id'] for r in rows};assert len(tasks)==20
 for task in tasks:
  for rep in (1,2,3):
   rs=[r for r in rows if r['task_id']==task and r['replicate']==rep];assert len(rs)==6
   assert len({r['initial_submission_sha256'] for r in rs})==len({r['selected_rubric_sha256'] for r in rs})==1
 spec=importlib.util.spec_from_file_location('native_analysis',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=module.aggregate(rows,panel)
 contrast=module.paired_contrast(rows,'trace/user-simulator-red-team-trace','static/user-simulator-static',panel)
 payload=dict(rows=rows,conditions=conditions,monitor_distributions=distributions,contrasts={'trace minus static':contrast,'update minus static':module.paired_contrast(rows,'update/user-simulator-red-team-trace','static/user-simulator-static',panel),'update minus trace':module.paired_contrast(rows,'update/user-simulator-red-team-trace','trace/user-simulator-red-team-trace',panel)},coverage=coverage,sources=sources,definitions=reference['definitions'],uncertainty=reference['uncertainty'])
 pretreatment_path=BASE/'pretreatment-comparison.json'
 pretreatment=json.loads(pretreatment_path.read_text())
 assert len(pretreatment['rows'])==20
 for entry in pretreatment['rows']:
  assert sha(entry['old_path'])==entry['old_sha256'] and sha(entry['new_path'])==entry['new_sha256']
 payload['starting_criterion_comparison']=dict(source=str(pretreatment_path),source_sha256=sha(pretreatment_path),changed_tasks=pretreatment['changed_tasks'],rows=pretreatment['rows'],limitation='Realized starting criteria were reinduced, so differences cannot be attributed solely to update-note delivery. All tasks remain in the primary outcome population.')
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
 intro=['# New-criterion delivery: matched static, trace and update Result20','','Twenty canonical tasks × three replicates per condition. All180 assignments/360auditor rows validated; seeds and selected rubrics matched. Primary detectors, models and thresholds unchanged. Earlier fidelity replays and bounded-score cohorts are excluded from this comparison. This is developmental Result20, not untouched confirmation.','','Pretreatment was independently reinduced: identical protocol settings do not guarantee identical realized starting criteria. This comparison cannot isolate delivery alone without checking that variation. See criterion-update-pretreatment-caveat.md. Inspect actual feedback exposure alongside RH and quality. All arms use identical score-disclosing simulator wording; update adds only newly admitted requirement notes to the trace condition. Inspect policy admission and actual feedback exposure. Report null/adverse results.','']
 (ROOT/'docs/reports/2026-09-09/result20-criterion-update.md').write_text('\n'.join(intro+comparison_details(payload,render)+['','## Feedback exposure and revision behavior','','Descriptive counts; not a causal mediation analysis. Full source-linked details are in comparison-v1/feedback-exposure.json.','','```json',json.dumps(exposure['conditions'],indent=2),'```','','## Score disclosure screen','',disclosure['caveat'],'','```json',json.dumps(disclosure['conditions'],indent=2),'```'])+'\n')
 (out/'receipt.json').write_text(json.dumps(dict(success=True,job_id=os.environ['SLURM_JOB_ID'],analysis_sha256=sha(out/'analysis.json'),script_sha256=sha(__file__)))+'\n')
if __name__=='__main__':main()
