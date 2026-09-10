"""Audit only valid completed cells after a declared infrastructure failure."""
import json,os,subprocess,sys,time,threading,hashlib
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.study import _exclusive_study_lease
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-result20-cue-score-bounded-20260909'
FAILED='da-13-3--rep-001--solver-luna--user-simulator-red-team-trace'
def main():
 assert os.environ.get('SLURM_JOB_ID')
 launch_path=next((BASE/'owners/static-results20').glob('10367784-*/launch.json'))
 launch=json.loads(launch_path.read_text());result=json.loads(launch_path.with_name('result.json').read_text());assert result['source_unchanged']
 assert subprocess.check_output(['squeue','-h','-j','10367784'],text=True).strip()==''
 study=json.loads((Path(launch['outputs']['revise']['output_dir'])/'study.json').read_text())
 selected=[r for r in study['records'] if r['condition_id']=='user-simulator-static']
 failed=[r for r in selected if r['status']!='completed']
 expected=json.loads((ROOT/'investigation/result20-cue-score-preempt-repair-20260909/invalid-source-records.json').read_text())
 assert len(selected)==60 and len(failed)==6 and {r['assignment_id'] for r in failed}=={r['assignment_id'] for r in expected}
 assert all(r['status']=='failed' and r['error']=='live workspace changed after the last checkpoint' for r in failed)

 for p,h in launch['source_hashes'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
 owner=BASE/'owners/survivor-audit';owner.mkdir(parents=True,exist_ok=True)
 with _exclusive_study_lease(owner):
  receipt=owner/os.environ['SLURM_JOB_ID'];receipt.mkdir(exist_ok=False)
  command=[str(Path(sys.executable).with_name('rubric-gen')),'detect','--experiment',launch['config'],'--max-concurrency','60','--resume']
  metadata=dict(job_id=os.environ['SLURM_JOB_ID'],source_launch=str(launch_path),source_commit=launch['git_commit'],command=command,expected_completed=54,excluded_infrastructure_assignments=[r["assignment_id"] for r in failed],policy=policy(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
  (receipt/'launch.json').write_text(json.dumps(metadata,indent=2)+'\n')
  for key,value in dotenv_values(ROOT/'.env.local').items():
   if key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY') and value:os.environ[key]=value
  sys.path.insert(0,str(CODE/'scripts/babel'));from monitor import Monitor
  monitor=Monitor(policy()['coordination_dir'],receipt/'metrics.jsonl',[])
  with (receipt/'detect.log').open('x') as log:
   child=subprocess.Popen(command,cwd=CODE,stdout=log,stderr=subprocess.STDOUT)
   while child.poll() is None:monitor.sample();time.sleep(10)
   code=child.wait()
  monitor.sample()
  for p,h in launch['source_hashes'].items():assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
  (receipt/'result.json').write_text(json.dumps(dict(success=code==0,exit=code,source_unchanged=True,expected_completed=54))+'\n')
  return code
if __name__=='__main__':raise SystemExit(main())
