"""Coverage-gated, read-only matched static/trace user Result20 comparison."""
import hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen')
BUNDLE=ROOT/'investigation/result20-report-20260908'
CODE=ROOT/'runs/babel-code/result20-checkpoint-recovery'
PRODUCERS={'user-static':('10357851','checkpoint','1f995dfa53cd51582ce2b3f84db78ceca055a4ea'),'user-trace':('10357630','local-temp','653584034445d39dc4429142d30481e1178ee6f0')}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 start=time.time();seal=json.loads((BUNDLE/'user-pair-seal.json').read_text())
 for name,value in seal.items():
  if sha(ROOT/name)!=value:raise RuntimeError('analysis source changed: '+name)
 output=ROOT/'runs/babel-result20-current-20260908/user-policy-comparison-v1'
 if output.exists():raise RuntimeError('report output already exists; reconcile its owner')
 receipt=ROOT/f'runs/babel-result20-current-20260908/user-pair-report-job-{os.environ["SLURM_JOB_ID"]}'
 receipt.mkdir(exist_ok=False)
 command=[sys.executable,str(CODE/'investigation/babel-overnight-20260907/analyze_babel.py')]
 evidence={}
 for mode,(job,kind,commit) in PRODUCERS.items():
  owner=ROOT/f'runs/babel-overnight-20260907/dispatcher-{mode}-result20-{kind}-recovery'
  matches=[p for p in owner.glob('*/launch.json') if json.loads(p.read_text())['job_id']==job]
  if len(matches)!=1:raise RuntimeError('ambiguous/missing producer '+mode)
  p=matches[0];launch=json.loads(p.read_text());result=json.loads((p.parent/'result.json').read_text())
  if result!={'exits':[0,0],'source_unchanged':True,'success':True}:raise RuntimeError('producer incomplete '+mode)
  if launch['git_commit']!=commit:raise RuntimeError('producer commit mismatch '+mode)
  for name,value in launch['source_hashes'].items():
   if sha(name)!=value:raise RuntimeError('producer source changed: '+name)
  base=ROOT/f'runs/babel-result20-current-20260908/{mode}';identity=launch['experiment_id']
  command+=['--study',str(base/'study'/identity),'--audit',str(base/'audit'/identity)]
  evidence[mode]={'job':job,'receipt':str(p),'receipt_sha256':sha(p),'result_sha256':sha(p.parent/'result.json'),'commit':commit}
 for left,right in [('user-simulator-static','user-simulator-red-team-trace')]:command+=['--contrast',left,right]
 command+=['--output',str(output)]
 commands=[command]
 (receipt/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),source_seal=seal,producers=evidence,commands=commands,output=str(output),scope='120 matched user static/trace assignments,complete Sol+Opus audits; no providers'),indent=2)+'\n')
 exits=[]
 for index,cmd in enumerate(commands):
  with (receipt/f'stage-{index}.log').open('w') as log:exits.append(subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode)
  if exits[-1]:break
 unchanged=all(sha(ROOT/n)==h for n,h in seal.items())
 success=exits==[0] and unchanged
 (receipt/'result.json').write_text(json.dumps(dict(success=success,exits=exits,source_unchanged=unchanged,elapsed_seconds=time.time()-start))+'\n')
 return 0 if success else 1
if __name__=='__main__':raise SystemExit(main())
