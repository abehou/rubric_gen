"""Private two-case sidecar mechanism check; no solver cohort or outcome audit."""
import hashlib,json,os,subprocess
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.red_team import RedTeamGenerator
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.artifacts import tree_sha256
ROOT=Path('/home/aydanh/repos/rubric_gen')
CODE=ROOT/'runs/babel-code/result20-input-provenance'
CONFIG=ROOT/'investigation/result20-cue-score-first-trace-20260909/trace-results20.yaml'
def main():
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm required')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()
    if not commit.startswith('a1e8ec2'):raise RuntimeError('wrong source')
    exp=load_experiment(CONFIG)
    out=ROOT/'runs'/f'input-provenance-mechanism-{os.environ["SLURM_JOB_ID"]}'
    out.mkdir(exist_ok=False)
    source_root=ROOT/'runs/babel-result20-cue-score-first-trace-20260909/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-12-2'
    inputs=[]
    for rep in ('rep-002','rep-003'):
        revision=source_root/rep/'luna/user-simulator-red-team-trace'
        workspace=revision/'submissions/s001/workspace'
        generation=load_rubric_generation(revision,1)
        inputs.append((rep,workspace,generation,tree_sha256(workspace),tree_sha256(exp.task_dir('da-12-2'))))
    frozen={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE.joinpath('src').rglob('*.py')}
    frozen[str(CONFIG)]=hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    frozen[str(Path(__file__).resolve())]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    receipt=dict(job_id=os.environ['SLURM_JOB_ID'],commit=commit,config=str(CONFIG),source_hashes=frozen,inputs=[dict(replicate=r,workspace=str(w),workspace_sha256=h,task_sha256=t,generation_sha256=g.generation_sha256) for r,w,g,h,t in inputs],kind='synthetic-sidecar-mechanism-check')
    (out/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
    keys=dotenv_values(ROOT/'.env.local')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        if keys.get(key):os.environ[key]=keys[key]
    generator=RedTeamGenerator(agent=exp.red_team_agent_config(),benchmark=get_submission_benchmark(exp.benchmark))
    results=[]
    for rep,workspace,generation,source_hash,task_hash in inputs:
        result=generator.ensure(task_dir=exp.task_dir('da-12-2'),source_workspace=workspace,active_generation=generation,checkpoint=1,experiment_dir=out/rep)
        assert tree_sha256(workspace)==source_hash and tree_sha256(exp.task_dir('da-12-2'))==task_hash
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in frozen.items())
        results.append(dict(replicate=rep,included=result.included,root=str(result.root)))
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    (out/'complete.json').write_text(json.dumps(dict(execution_completed=True,scientific_acceptance='pending artifact inspection and native induction',results=results))+'\n')
if __name__=='__main__':main()
