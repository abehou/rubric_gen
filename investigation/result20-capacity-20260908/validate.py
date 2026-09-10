"""Read-only current-format input and scientific-diff validation."""
import hashlib,json,os,socket
from pathlib import Path
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.judging.executor import JudgeExecutor
ROOT=Path('/home/aydanh/repos/rubric_gen')
old=ROOT/'runs/babel-code/result20-current/experiments/babel/biomnibench-result20-current-user-trace.yaml'
new=CODE/'experiments/babel/biomnibench-result20-capacity-user-trace.yaml'
assert old.read_text().replace('babel-result20-current-20260908/user-trace','babel-result20-capacity-20260908/user-trace')==new.read_text()
a,b=load_experiment(old),load_experiment(new)
assert a.experiment_id==b.experiment_id and len(b.task_ids)==20 and b.replicates==3
assert a.protocol==b.protocol and a.task_ids==b.task_ids
for stage in ['seed','paraphrase']:assert a.dag[stage]==b.dag[stage]
validate_paraphrase_run(Path(b.dag['paraphrase']['output_dir']),b)
seeds=[]
for task in b.task_ids:
 for rep in range(1,4):
  v=resolve_seed(Path(b.dag['seed']['output_dir']),b.task_dir(task),rep,seed_generator=b.seed_agent_config(),prompt_profile=b.protocol['prompt'],benchmark=b.benchmark)
  assert v.manifest['scoring_identity']['scoring_implementation_sha256']==JudgeExecutor.scoring_implementation_sha256(b.benchmark)
  seeds.append([task,rep])
base=ROOT/'runs/babel-code/result20-checkpoint-recovery'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
changed=[str(p.relative_to(CODE)) for p in (CODE/'src').rglob('*.py') if sha(p)!=sha(base/p.relative_to(CODE))]
assert set(changed)=={'src/rubric_gen/submission_revision/evolution_validation.py','src/rubric_gen/submission_revision/evolution_provider.py'}
for n in ['uv.lock','pyproject.toml','config/runtime.json']:assert sha(CODE/n)==sha(base/n)
out=ROOT/f'runs/babel-result20-capacity-20260908/input-validation-{os.environ["SLURM_JOB_ID"]}';out.mkdir(parents=True,exist_ok=False)
result=dict(success=True,job=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),experiment_id=b.experiment_id,seed_count=len(seeds),tasks=list(b.task_ids),replicates=3,changed_source=changed,source_hashes={n:sha(CODE/n) for n in changed},config_sha256=sha(new),script_sha256=sha(Path(__file__)),scientific_change='none;new output roots,recorded4MiB ceiling,bounded4-wayvalidation',provider_calls=0)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
