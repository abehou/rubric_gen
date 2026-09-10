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
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip();assert commit.startswith('4d5c2d0')
assert PROPOSER_MAX_OUTPUT_TOKENS==65536 and PROPOSER_MAX_REQUEST_BYTES==4194304
changes=subprocess.check_output(['git','diff','0fbe0bb',commit,'--name-only','--','src'],cwd=ROOT,text=True).splitlines()
assert set(changes)=={'src/rubric_gen/submission_revision/user_simulator.py','src/rubric_gen/submission_revision/artifacts.py','src/rubric_gen/submission_revision/contrasts.py','src/rubric_gen/submission_revision/execution_scope.py','src/rubric_gen/submission_revision/experiment.py','src/rubric_gen/submission_revision/study.py','src/rubric_gen/submission_revision/pretreatment_reuse.py','src/rubric_gen/submission_revision/evolution.py'}
parent=ROOT/'runs/babel-code/result20-cue-contrast'
for name in ('uv.lock','pyproject.toml','config/runtime.json'):assert sha(PROJECT_ROOT/name)==sha(parent/name)
source={str(p):sha(p) for p in (PROJECT_ROOT/'src').rglob('*.py')}
old=yaml.safe_load((ROOT/'investigation/result20-cue-contrast-20260908/static-results20.yaml').read_text());rows=[]
for arm,condition in [('static','user-simulator-static')]:
 p=BUNDLE/f'{arm}-results20.yaml';raw=yaml.safe_load(p.read_text());normalized=yaml.safe_load(p.read_text())
 assert normalized.pop('execution_assignment_ids')==['da-10-3--rep-002--solver-luna--user-simulator-static', 'da-12-4--rep-002--solver-luna--user-simulator-static', 'da-13-1--rep-002--solver-luna--user-simulator-static', 'da-14-8--rep-001--solver-luna--user-simulator-static', 'da-16-1--rep-001--solver-luna--user-simulator-static', 'da-19-1--rep-002--solver-luna--user-simulator-static']
 normalized['execution_conditions']=old['execution_conditions']
 for stage in ('revise','detect'):normalized['dag'][stage]['output_dir']=old['dag'][stage]['output_dir']
 assert normalized==old,'Other Result20 scientific settings changed'
 exp=load_experiment(p);assert len(exp.task_ids)==20 and exp.replicates==3 and len(exp.execution_assignments)==6
 assert raw['execution_conditions']==[condition]
 for task in exp.task_ids:
  for rep in (1,2,3):resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
 validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
 rows.append(dict(arm=arm,task='results20',config=str(p),config_sha256=sha(p),assignments=6,native_seeds=60,paraphrases_valid=True))
out=ROOT/f'runs/result20-cue-score-repair-input-validation-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
tests=['test_red_team.py','test_submission_revision_artifacts.py','test_rubric_generation.py','test_runtime_capacity.py']
with (out/'tests.log').open('w') as stream:r=subprocess.run([sys.executable,'-m','pytest','-q',*[f'tests/{t}' for t in tests]],cwd=PROJECT_ROOT,stdout=stream,stderr=subprocess.STDOUT)
unchanged=all(sha(p)==h for p,h in source.items())
(out/'result.json').write_text(json.dumps(dict(success=r.returncode==0 and unchanged,commit=commit,inputs=rows,source_hashes=source,source_unchanged=unchanged,test_exit=r.returncode,job=os.environ['SLURM_JOB_ID']),indent=2)+'\n')
if r.returncode==0 and unchanged:
 (BUNDLE/'acceptance.json').write_bytes((out/'result.json').read_bytes())
sys.exit(r.returncode or int(not unchanged))
