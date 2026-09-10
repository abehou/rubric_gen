"""Read-only native validation of existing dev3 inputs; no provider calls."""
import hashlib,json,os,subprocess
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.runtime.paths import PROJECT_ROOT
ROOT=Path('/home/aydanh/repos/rubric_gen')
assert os.environ.get('SLURM_JOB_ID')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip()=='5270c4aafcac67adc2ff67f63b9595112d16202a'
results=[]
for task in ['da-3-4','da-11-1']:
 p=ROOT/f'experiments/babel/biomnibench-dev3-control-{task}.yaml'
 row={'task':task,'config':str(p),'config_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'seeds':[]}
 try:
  exp=load_experiment(p)
  for rep in range(1,4):
   try:
    seed=resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
    row['seeds'].append({'replicate':rep,'valid':True})
   except Exception as e:row['seeds'].append({'replicate':rep,'valid':False,'error_class':type(e).__name__,'error':str(e)[:800]})
  try:validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp);row['paraphrases_valid']=True
  except Exception as e:row.update(paraphrases_valid=False,paraphrase_error_class=type(e).__name__,paraphrase_error=str(e)[:800])
 except Exception as e:row.update(config_valid=False,error_class=type(e).__name__,error=str(e)[:800])
 results.append(row)
p=ROOT/'experiments/biomnibench-dev3.yaml';exp=load_experiment(p)
canonical={'tasks':exp.task_ids,'replicates':exp.replicates,'randomization':exp.randomization if hasattr(exp,'randomization') else None,'seed_pool_exists':Path(exp.dag['seed']['output_dir']).exists(),'paraphrase_pool_exists':Path(exp.dag['paraphrase']['output_dir']).exists(),'da18_instruction_exists':(exp.task_dir('da-18-1')/'instruction.md').is_file()}
out=ROOT/f'runs/babel-dev3-input-readiness-20260908/{os.environ["SLURM_JOB_ID"]}';out.mkdir(parents=True,exist_ok=False)
result={'job':os.environ['SLURM_JOB_ID'],'source':str(PROJECT_ROOT),'commit':'5270c4a','scope':'Read-only current-format validation;no generation or metadata modification','existing_tuning_pools':results,'canonical':canonical}
(out/'result.json').write_text(json.dumps(result,indent=2,default=str)+'\n');print(json.dumps(result,indent=2,default=str))
