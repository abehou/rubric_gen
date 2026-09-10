"""Audit completed original assignments under their actual producing source."""
import os,json,hashlib,subprocess,sys,socket
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE
from rubric_gen.submission_revision.experiment import load_experiment
ROOT=Path('/home/aydanh/repos/rubric_gen')
BASE=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
assert os.environ.get('SLURM_JOB_ID')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()=='c507d402a953dde9bf5177ca9eafb78bcbce7df4'
old=json.loads(next((BASE/'owners/trace-results20').glob('10373129-*/launch.json')).read_text())
original=ROOT/'runs/babel-code/result20-cue-active-violations'
for name,digest in old['source_hashes'].items():
 path=Path(name)
 if path.is_relative_to(original):
  target=CODE/path.relative_to(original)
  assert hashlib.sha256(target.read_bytes()).hexdigest()==digest,str(target)
exp=load_experiment(ROOT/'investigation/result20-cue-active-violations-20260909/trace-results20.yaml')
ledger=json.loads((Path(exp.dag['revise']['output_dir'])/'study.json').read_text())
from rubric_gen.submission_revision.execution_scope import terminal_records
records=terminal_records(exp,ledger)
assert sum(r['status']=='completed' for r in records)==59
assert [r['assignment_id'] for r in records if r['status']!='completed']==['da-14-3--rep-001--solver-luna--user-simulator-red-team-trace']
receipt=BASE/'audit-owners'/os.environ['SLURM_JOB_ID'];receipt.mkdir(parents=True,exist_ok=False)
cmd=[str(Path(sys.executable).with_name('rubric-gen')),'detect','--experiment',str(exp.path),'--max-concurrency','60','--resume']
(receipt/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),commit='c507d402a953dde9bf5177ca9eafb78bcbce7df4',command=cmd,source_owner=old['job_id'],completed_assignments=59),indent=2))
for k,v in dotenv_values(ROOT/'.env.local').items():
 if k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY') and v:os.environ[k]=v
with (receipt/'detect.log').open('x') as f:result=subprocess.run(cmd,cwd=CODE,stdout=f,stderr=subprocess.STDOUT)
(receipt/'result.json').write_text(json.dumps(dict(exit_code=result.returncode,success=result.returncode==0)))
raise SystemExit(result.returncode)
