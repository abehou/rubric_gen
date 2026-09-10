"""Isolated native generation-2 replay with the verified synthetic contrast."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.red_team import RedTeamGenerator
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.rubric_generation import CompleteRubric,RubricPolicy
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.contrasts import build_elicitation_artifact_history
from rubric_gen.submission_revision.pretreatment_rubrics import pretreatment_blinding_scope
from rubric_gen.submission_revision.artifacts import tree_sha256
ROOT=Path('/home/aydanh/repos/rubric_gen')
CODE=ROOT/'runs/babel-code/result20-input-provenance'
CONFIG=ROOT/'investigation/result20-cue-score-first-trace-20260909/trace-results20.yaml'
def main():
    assert os.environ.get('SLURM_JOB_ID'), 'Slurm required'
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()
    assert commit.startswith('a1e8ec2')
    exp=load_experiment(CONFIG); task=exp.task_dir('da-12-2')
    source=ROOT/'runs/babel-result20-cue-score-first-trace-20260909/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments/da-12-2/rep-003/luna/user-simulator-red-team-trace'
    sidecar=ROOT/'runs/input-provenance-mechanism-10369662/rep-003/red-team/checkpoint-0001'
    m=json.loads((source/'manifest.json').read_text())
    out=ROOT/'runs'/f'input-provenance-induction-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
    inputs=[source/'submissions/s000/workspace',source/'submissions/s001/workspace',sidecar,source/'rubric-generations/generation-0001']
    hashes={str(p):tree_sha256(p) for p in inputs}
    frozen={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in CODE.joinpath('src').rglob('*.py')}
    for p in [CONFIG,Path(__file__),Path(m['initial_rubric_path']),Path(m['development_rubric_path']),task/'instruction.md']:
        frozen[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    (out/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],hostname=os.uname().nodename,commit=commit,kind='isolated-native-induction-not-study-resume',inputs=hashes,source_hashes=frozen),indent=2)+'\n')
    for checkpoint in ('s000','s001'):
        shutil.copytree(source/'submissions'/checkpoint/'workspace',out/'submissions'/checkpoint/'workspace')
    shutil.copytree(sidecar,out/'red-team/checkpoint-0001')
    current=load_rubric_generation(source,1)
    original=CompleteRubric.from_content(Path(m['initial_rubric_path']).read_text())
    development=CompleteRubric.from_content(Path(m['development_rubric_path']).read_text())
    pretreatment=json.loads((Path(m['pretreatment_rubric_dir'])/'pretreatment.json').read_text())
    benchmark=get_submission_benchmark(exp.benchmark)
    generator=RedTeamGenerator(agent=exp.red_team_agent_config(),benchmark=benchmark)
    history=build_elicitation_artifact_history(online=True,seed_set=Path(m['seed_run_dir']),task_dir=task,experiment_dir=out,benchmark=benchmark,seed_generator=exp.seed_agent_config(),prompt_profile=m['prompt'],seed_replicates=m['elicitation_seed_replicates'],blinding_scope=pretreatment_blinding_scope(pretreatment['experiment_id'],task.name,original.content_sha256,development.content_sha256),source_checkpoint=1,red_team_policy=RubricPolicy.RED_TEAM_TRACE,red_team_generator_identity=generator.identity())
    (out/'input-validation.json').write_text(json.dumps(dict(artifacts=len(history.artifacts),pairs=len(history.pairs),red_team_evidence=len(history.red_team_evidence)))+'\n')
    assert len(history.red_team_evidence)==1
    for key,value in dotenv_values(ROOT/'.env.local').items():
        if key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY') and value:os.environ[key]=value
    proposer=RubricProposer(benchmark=exp.benchmark,model=m['rubric_proposer_model'],max_retries=m['rubric_proposer_max_retries'],service_tier=m['service_tier'])
    generation=proposer.elicit_rubric(instruction=(task/'instruction.md').read_text(),original_rubric=original,development_rubric=development,current_generation=current,policy=RubricPolicy.RED_TEAM_TRACE,generation_round=2,output_dir=out,artifact_history=history,source_checkpoint=1)
    generation.validate_successor(current)
    assert all(tree_sha256(Path(p))==h for p,h in hashes.items())
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in frozen.items())
    (out/'complete.json').write_text(json.dumps(dict(success=True,generation_sha256=generation.generation_sha256,interpretation='pending criterion and admission inspection; no natural RH outcome'))+'\n')
if __name__=='__main__':main()
