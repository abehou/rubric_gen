"""Combine complete native reports across explicitly recorded runtime attempts."""
import argparse,hashlib,importlib.util,json,os,socket,sys,time
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
CODE=ROOT/'runs/babel-code/result20-checkpoint-recovery'
PANEL=['gpt-5.6-sol','claude-opus-5']
CATALOG={
 'full-static':('runs/babel-result20-current-20260908/full-static-report-v2','runs/babel-result20-current-20260908/static-report-job-10357605','10357585'),
 'user-simulator-static':('runs/babel-result20-current-20260908/user-static-report-v1','runs/babel-result20-current-20260908/user-static-report-job-10357863','10357851'),
 'user-simulator-red-team-trace':('runs/babel-result20-capacity-v3-20260908/user-trace-report-v1','runs/babel-result20-capacity-v3-20260908/user-trace-report-job-10359080','10358980'),
 'full-red-team-trace':('runs/babel-result20-current-20260908/full-trace-report-v1','runs/babel-result20-current-20260908/full-trace-report-job-10359310','10359309'),
}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['static-check','user-policy','full-policy','combined']);a=p.parse_args();start=time.time()
 seal=json.loads((BUNDLE/'combine-full-pair-seal.json').read_text())
 for n,h in seal.items():assert sha(ROOT/n)==h,n
 module_path=CODE/'investigation/babel-overnight-20260907/analyze_babel.py'
 spec=importlib.util.spec_from_file_location('frozen_analysis',module_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
 names={'static-check':['full-static','user-simulator-static'],'user-policy':['user-simulator-static','user-simulator-red-team-trace'],'full-policy':['full-static','full-red-team-trace'],'combined':list(CATALOG)}[a.mode]
 contrasts={'static-check':[('full-static','user-simulator-static')],'user-policy':[('user-simulator-static','user-simulator-red-team-trace')],'full-policy':[('full-static','full-red-team-trace')],'combined':[('full-static','user-simulator-static'),('full-static','full-red-team-trace'),('user-simulator-static','user-simulator-red-team-trace')]}[a.mode]
 outputs={'static-check':'validated-static-check-v2','user-policy':'user-policy-comparison-v2','full-policy':'full-policy-comparison-v1','combined':'report-v2'}
 output=ROOT/'runs/babel-result20-current-20260908'/outputs[a.mode]
 if output.exists():raise RuntimeError('output already exists; reconcile its owner')
 rows=[];coverage=[];origins={};reference=None;keys=set();tasks=None
 for name in names:
  folder,receipt,producer=CATALOG[name];folder=ROOT/folder;receipt=ROOT/receipt
  result=json.loads((receipt/'result.json').read_text());launch=json.loads((receipt/'launch.json').read_text())
  assert result['success'] is True and result['source_unchanged'] is True and result['exit_code']==0
  assert str(launch['producer_job'])==producer and Path(launch['output'])==folder
  for n,h in launch['source_seal'].items():assert sha(ROOT/n)==h,n
  path=folder/'analysis.json';data=json.loads(path.read_text())
  assert data['analysis_source_sha256']==sha(module_path)
  assert len(data['coverage'])==1 and data['coverage'][0]['assignment_count']==60 and len(data['rows'])==120
  scoped={(r['task_id'],r['replicate'],r['model']) for r in data['rows']}
  ids={r['task_id'] for r in data['rows']};assert len(ids)==20
  assert scoped=={(task,rep,model) for task in ids for rep in [1,2,3] for model in PANEL}
  if tasks is None:tasks=ids
  assert tasks==ids
  for row in data['rows']:
   assert row['analysis_condition']==row['condition_id']==name
   key=(name,row['task_id'],row['replicate'],row['model']);assert key not in keys;keys.add(key)
   assert sha(row['state_path'])==row['state_sha256']
   assert sha(row['score_composition_path'])==row['score_composition_sha256']
  if reference is None:reference=data
  assert data['definitions']==reference['definitions'] and data['uncertainty']==reference['uncertainty']
  rows+=data['rows'];coverage+=data['coverage']
  origins[name]=dict(report=str(path),sha256=sha(path),receipt=str(receipt),result_sha256=sha(receipt/'result.json'),producer_job=producer,native_source_seal=launch['source_seal'])
 conditions,distributions=helper.aggregate(rows,PANEL)
 payload=dict(coverage=coverage,rows=rows,conditions=conditions,contrasts={f'{l} minus {r}':helper.paired_contrast(rows,l,r,PANEL) for l,r in contrasts},monitor_distributions=distributions,definitions=reference['definitions'],uncertainty=reference['uncertainty'],analysis_source_sha256=sha(module_path),source_analyses=origins,combination_scope='Complete separately native-validated conditions;exact same frozen numeric/statistical functions;runtime versions remain recorded,not relabeled')
 if a.mode=='static-check':
  expected=json.loads((ROOT/'runs/babel-result20-current-20260908/static-comparison-v1/analysis.json').read_text())
  for field in ['rows','conditions','contrasts','monitor_distributions']:assert json.loads(json.dumps(payload[field]))==expected[field],field
 output.mkdir(parents=True,exist_ok=False);(output/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
 unchanged=all(sha(ROOT/n)==h for n,h in seal.items())
 (output/'combination-receipt.json').write_text(json.dumps(dict(success=unchanged,source_unchanged=unchanged,source_seal=seal,job=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),mode=a.mode,seconds=time.time()-start,analysis_sha256=sha(output/'analysis.json')),indent=2)+'\n')
 print(json.dumps(dict(success=unchanged,mode=a.mode,assignments=len(rows)//2,output=str(output))));return int(not unchanged)
if __name__=='__main__':raise SystemExit(main())
