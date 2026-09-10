"""Generate only missing additional-task paraphrases; never invoke another stage."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dotenv import load_dotenv
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run

ROOT=Path('/home/aydanh/repos/rubric_gen')
B=ROOT/'investigation/confirmation-pools-20260909'
assert os.environ.get('SLURM_JOB_ID')
validation=ROOT/'runs/confirmation-data-validated-10372829/result.json'
assert json.loads(validation.read_text())['success']
load_dotenv(ROOT/'.env.local',override=False)
OUT=ROOT/('runs/confirmation-paraphrases-'+os.environ['SLURM_JOB_ID'])
OUT.mkdir(exist_ok=False)
old=ROOT/'runs/babel-result20-input-restore-10356965/archive-inputs/runs/rubric-paraphrases/biomnibench/red-team-results20'
def hashes(root):
    result={}
    for p in sorted(root.rglob('*')):
        assert not p.is_symlink()
        if p.is_file():result[str(p.relative_to(root))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result
consumers={(g,a):load_experiment(B/f'pool-{g}-{a}.yaml') for g in ('original20','additional25') for a in ('static','trace')}
before=hashes(old)
for a in ('static','trace'):validate_paraphrase_run(old,consumers['original20',a])
target=Path(consumers['original20','static'].dag['paraphrase']['output_dir'])
if not target.exists():shutil.copytree(old,target)
assert hashes(target)==before and hashes(old)==before
for a in ('static','trace'):validate_paraphrase_run(target,consumers['original20',a])
config=B/'pool-additional25-static.yaml'
with (OUT/'generate.log').open('x') as log:
    result=subprocess.run([sys.executable,'-c','from rubric_gen.cli import main; main()','paraphrase','--experiment',str(config),'--max-concurrency','60'],stdout=log,stderr=subprocess.STDOUT)
assert result.returncode==0, 'Paraphrase-only stage failed; preserve successes and inspect native resume'
pool=Path(consumers['additional25','static'].dag['paraphrase']['output_dir'])
for a in ('static','trace'):validate_paraphrase_run(pool,consumers['additional25',a])
assert hashes(old)==before
inventories={str(target):hashes(target),str(pool):hashes(pool)}
for root in (target,pool):
    for p in root.rglob('*'):p.chmod(0o555 if p.is_dir() else 0o444)
    root.chmod(0o555)
(OUT/'result.json').write_text(json.dumps(dict(success=True,job_id=os.environ['SLURM_JOB_ID'],tasks=45,variants=225,
    reused_tasks=20,generated_tasks=25,matched_consumers_validated=True,pools=inventories,
    data_validation_sha256=hashlib.sha256(validation.read_bytes()).hexdigest()),indent=2)+'\n')
