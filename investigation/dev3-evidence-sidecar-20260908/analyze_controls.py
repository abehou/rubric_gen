"""Read-only native validation of all canonical dev3 static/current-trace controls."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-dev3-evidence-sidecar-20260908';CODE=ROOT/'runs/babel-code/dev3-evidence-control'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 assert os.environ.get('SLURM_JOB_ID')
 out=BASE/'canonical-controls-v1';out.mkdir(exist_ok=False);rows=[];coverage=[];sources=[];reference=None
 helper=CODE/'investigation/babel-overnight-20260907/analyze_babel.py'
 for task,job in [('da-11-1','10363145'),('da-3-4','10364286'),('da-18-1','10364289')]:
  receipts=list((BASE/f'owners/control-{task}').glob(f'{job}-*/launch.json'));assert len(receipts)==1
  p=receipts[0];launch=json.loads(p.read_text());result=json.loads(p.with_name('result.json').read_text());assert result['success'] and result['source_unchanged']
  for name,h in launch['source_hashes'].items():assert sha(name)==h,name
  native=out/task
  with (out/f'{task}.log').open('x') as f:subprocess.run([sys.executable,str(helper),'--study',launch['outputs']['revise']['output_dir'],'--audit',launch['outputs']['detect']['output_dir'],'--output',str(native),'--label','control'],cwd=CODE,env=dict(os.environ,PYTHONPATH=str(CODE/'src')),stdout=f,stderr=subprocess.STDOUT,check=True)
  d=json.loads((native/'analysis.json').read_text());assert len(d['rows'])==12 and {r['task_id'] for r in d['rows']}=={task}
  if reference is None:reference=d
  assert d['definitions']==reference['definitions'] and d['uncertainty']==reference['uncertainty']
  rows+=d['rows'];coverage+=d['coverage'];sources.append(dict(task=task,job=job,launch=str(p),sha256=sha(p),analysis_sha256=sha(native/'analysis.json')))
 assert len(rows)==36
 for task in {r['task_id'] for r in rows}:
  for rep in (1,2,3):
   rs=[r for r in rows if r['task_id']==task and r['replicate']==rep];assert len(rs)==4 and len({r['initial_submission_sha256'] for r in rs})==len({r['selected_rubric_sha256'] for r in rs})==1
 spec=importlib.util.spec_from_file_location('native_analysis',helper);h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
 panel=['gpt-5.6-sol','claude-opus-5'];conditions,distributions=h.aggregate(rows,panel)
 data=dict(rows=rows,coverage=coverage,sources=sources,conditions=conditions,monitor_distributions=distributions,definitions=reference['definitions'],uncertainty=reference['uncertainty'],contrasts={'trace minus static':h.paired_contrast(rows,'control/user-simulator-red-team-trace','control/user-simulator-static',panel)})
 (out/'analysis.json').write_text(json.dumps(data,indent=2)+'\n')
 renderer=Path(__file__).with_name('report_details.py');spec=importlib.util.spec_from_file_location('details',renderer);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 text=['# Canonical dev3 controls','','All three canonical tasks × three frozen replicates × static/current trace. Native source, full Sol/Opus coverage and matched seed/selected rubric checks passed. Original simulator and policy controls; do not mix these labels with the newer rubric-cue condition.','']+m.details(data)
 (ROOT/'docs/reports/2026-09-08/dev3-canonical-controls.md').write_text('\n'.join(text))
 (out/'receipt.json').write_text(json.dumps(dict(success=True,job=os.environ['SLURM_JOB_ID'],analysis_sha256=sha(out/'analysis.json'),script_sha256=sha(__file__),renderer_sha256=sha(renderer)))+'\n')
if __name__=='__main__':main()
