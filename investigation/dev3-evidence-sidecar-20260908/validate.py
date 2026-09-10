"""No-provider acceptance of isolated prompt sources and canonical dev3 pools."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.runtime.paths import PROJECT_ROOT
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
arm=sys.argv[1];assert arm in {'control','evidence'} and os.environ.get('SLURM_JOB_ID')
expected='6498d78' if arm=='control' else '4a8cebe'
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip();assert commit.startswith(expected)
diff=subprocess.check_output(['git','diff','6498d78','4a8cebe','--name-only'],cwd=ROOT,text=True).splitlines();assert diff==['src/rubric_gen/submission_revision/red_team.py'],diff
source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (PROJECT_ROOT/'src').rglob('*.py')}
out=ROOT/f'runs/dev3-evidence-validation-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
from rubric_gen.submission_revision.evolution_provider import PROPOSER_MAX_OUTPUT_TOKENS, PROPOSER_MAX_REQUEST_BYTES
assert PROPOSER_MAX_OUTPUT_TOKENS==65536 and PROPOSER_MAX_REQUEST_BYTES==4*1024*1024
rows=[]
for task in ['da-3-4','da-11-1','da-18-1']:
 p=BUNDLE/f'{arm}-{task}.yaml';exp=load_experiment(p)
 assert exp.replicates==3 and list(exp.task_ids)==[task]
 for rep in range(1,4):resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
 validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
 rows.append(dict(task=task,config=str(p),config_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),native_seed_count=3,native_paraphrases_valid=True))
tests=['test_rubric_evolution.py','test_red_team.py','test_pretreatment_reuse.py','test_submission_revision.py','test_submission_revision_artifacts.py','test_rubric_generation.py','test_architecture.py','test_runtime_capacity.py','test_babel_launcher.py','test_babel_portability.py']
with (out/'tests.log').open('w') as f:r=subprocess.run([sys.executable,'-m','pytest','-q',*[f'tests/{x}' for x in tests]],cwd=PROJECT_ROOT,stdout=f,stderr=subprocess.STDOUT)
unchanged=all(hashlib.sha256(Path(n).read_bytes()).hexdigest()==h for n,h in source.items())
(out/'result.json').write_text(json.dumps(dict(job=os.environ['SLURM_JOB_ID'],arm=arm,commit=commit,inputs=rows,source_hashes=source,source_unchanged=unchanged,test_exit=r.returncode,success=unchanged and r.returncode==0),indent=2)+'\n')
raise SystemExit(r.returncode or int(not unchanged))
