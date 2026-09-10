"""Accept matched Result20 configuration and combined prompt source without APIs."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
import yaml
from rubric_gen.runtime.paths import PROJECT_ROOT
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.evolution_provider import PROPOSER_MAX_OUTPUT_TOKENS,PROPOSER_MAX_REQUEST_BYTES
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
assert os.environ.get('SLURM_JOB_ID')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip();assert commit=='a587028c4c66f2c40cd9ff922fe7723861385891'
assert PROPOSER_MAX_OUTPUT_TOKENS==65536 and PROPOSER_MAX_REQUEST_BYTES==4194304
changes=subprocess.check_output(['git','diff','3f9d81b',commit,'--name-only','--','src'],cwd=ROOT,text=True).splitlines()
assert set(changes)=={'src/rubric_gen/submission_revision/contrasts.py','src/rubric_gen/submission_revision/experiment.py','src/rubric_gen/submission_revision/study.py','src/rubric_gen/submission_revision/execution_scope.py'}
parent=ROOT/'runs/babel-code/result20-crossfile-consistency'
for name in ('uv.lock','pyproject.toml','config/runtime.json'):assert sha(PROJECT_ROOT/name)==sha(parent/name)
source={str(p):sha(p) for p in (PROJECT_ROOT/'src').rglob('*.py')}
old=yaml.safe_load((ROOT/'investigation/result20-crossfile-consistency-20260908/trace-results20.yaml').read_text());rows=[]
for arm,condition in [('trace','user-simulator-red-team-trace')]:
 p=BUNDLE/f'{arm}-results20.yaml';raw=yaml.safe_load(p.read_text());normalized=yaml.safe_load(p.read_text())
 normalized.pop('execution_assignment_ids')
 normalized['execution_conditions']=old['execution_conditions']
 for stage in ('revise','detect'):normalized['dag'][stage]['output_dir']=old['dag'][stage]['output_dir']
 assert normalized==old,'Other Result20 scientific settings changed'
 exp=load_experiment(p);assert len(exp.task_ids)==20 and exp.replicates==3 and len(exp.execution_assignments)==1
 assert raw['execution_conditions']==[condition]
 for task in exp.task_ids:
  for rep in (1,2,3):resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
 validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
 rows.append(dict(arm=arm,task='results20',config=str(p),config_sha256=sha(p),assignments=1,native_seeds=60,paraphrases_valid=True))
out=ROOT/f'runs/result20-crossfile-pair-repair-validation-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
tests=['test_contrasts.py','test_red_team.py','test_rubric_evolution.py','test_experiment.py','test_execution_scope.py','test_babel_stage_recovery.py']
with (out/'tests.log').open('w') as stream:r=subprocess.run([sys.executable,'-m','pytest','-q',*[f'tests/{t}' for t in tests]],cwd=PROJECT_ROOT,stdout=stream,stderr=subprocess.STDOUT)
unchanged=all(sha(p)==h for p,h in source.items())
(out/'result.json').write_text(json.dumps(dict(success=r.returncode==0 and unchanged,commit=commit,inputs=rows,source_hashes=source,source_unchanged=unchanged,test_exit=r.returncode,job=os.environ['SLURM_JOB_ID']),indent=2)+'\n')
if r.returncode==0 and unchanged:
 (BUNDLE/'acceptance.json').write_bytes((out/'result.json').read_bytes())
sys.exit(r.returncode or int(not unchanged))
