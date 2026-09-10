import ast,hashlib,json,os,subprocess
from pathlib import Path
import yaml
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.study import StudyRunner,StudyRunConfig
from rubric_gen.submission_revision.evolution import RubricProposer
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent
assert os.environ.get('SLURM_JOB_ID')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip();assert commit.startswith('c507d40')
oldcode=ROOT/'runs/babel-code/result20-cue-contrast'
for f in ['user_simulator.py','red_team.py','contrasts.py']:
 rel=Path('src/rubric_gen/submission_revision')/f;assert sha(CODE/rel)==sha(oldcode/rel)
for f in ['uv.lock','pyproject.toml','config/runtime.json']:assert sha(CODE/f)==sha(oldcode/f)
def strings(p):
 return {n.targets[0].id:n.value.value for n in ast.parse(p.read_text()).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
rel=Path('src/rubric_gen/submission_revision/evolution_protocol.py');assert strings(CODE/rel)==strings(oldcode/rel)
old=yaml.safe_load((ROOT/'investigation/result20-cue-contrast-20260908/trace-results20.yaml').read_text());path=B/'trace-results20.yaml';raw=yaml.safe_load(path.read_text());normalized=yaml.safe_load(path.read_text());assert normalized['protocol'].pop('deliver_active_violations') is True;normalized.pop('pretreatment_source')
for stage in ['seed','paraphrase','revise','detect']:normalized['dag'][stage]['output_dir']=old['dag'][stage]['output_dir']
assert normalized==old
exp=load_experiment(path);assert len(exp.task_ids)==20 and exp.replicates==3 and len(exp.execution_assignments)==60
source={str(p):sha(p) for p in (CODE/'src').rglob('*.py')}
validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
for task in exp.task_ids:
 for rep in [1,2,3]:resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
out=ROOT/f'runs/cue-active-input-validation-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
large=Path('/data/user_data/aydanh/rubric_gen/validation')/out.name;large.mkdir(parents=True,exist_ok=False)
def forbidden(*a,**kw):raise AssertionError('provider forbidden')
RubricProposer._run_direct_proposer=forbidden
runner=StudyRunner(StudyRunConfig(exp,Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']),large/'input-consumer',60))
for task in exp.task_ids:runner._prepare_pretreatment_rubric(task)
assert all(sha(Path(p))==h for p,h in source.items())
result=dict(success=True,commit=commit,source_hashes=source,job_id=os.environ['SLURM_JOB_ID'],inputs=[dict(arm='trace',task='results20',config_sha256=sha(path),assignments=60,native_seeds=60,paraphrases_valid=True,pretreatment_tasks=20)],single_scientific_change='deliver currently violated elicited requirements')
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
with (B/'acceptance.json').open('x') as f:json.dump(result,f,indent=2)
print('Accepted: matched60assignments;60seeds;20frozen starting rubrics; unchanged cue prompts/auditors')
