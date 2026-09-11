"""Create only the dev3-compatible seed inputs for the v2.1 control."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json, os, socket, subprocess
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import SeedSetConfig, SeedSetRunner

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
FLAVOR = 'control-v21-compatible'
TASKS = ('da-3-4', 'da-11-1', 'da-18-1')
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911') / FLAVOR

def one(task):
    exp = load_experiment(BUNDLE / FLAVOR / f'{task}.yaml')
    result = SeedSetRunner(SeedSetConfig(exp, Path(exp.dag['seed']['output_dir']), 3)).run()
    return {'task': task, 'experiment_id': exp.experiment_id, 'exit_code': result, 'seed_root': exp.dag['seed']['output_dir'], 'config_sha256': sha256_file(exp.path)}

def main():
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('SLURM_CPUS_PER_TASK', '0')) != 32:
        raise RuntimeError('seed preparation requires a 32-CPU Slurm allocation')
    owner = RUN / 'owners' / ('seed-' + os.environ['SLURM_JOB_ID']); owner.mkdir(parents=True, exist_ok=True)
    launch = {'method':'attack_defense_v2.1','dev3_control_seed_derivation':True,'job':os.environ['SLURM_JOB_ID'],'host':socket.gethostname(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'tasks':list(TASKS),'time':datetime.now(timezone.utc).isoformat(),'provider_calls_expected':9}
    write_json_atomic(owner/'launch.json', launch)
    with ThreadPoolExecutor(max_workers=3) as pool: rows = list(pool.map(one, TASKS))
    if any(row['exit_code'] for row in rows): raise RuntimeError(f'seed derivation failed: {rows}')
    receipt={'method':'attack_defense_v2.1','job':os.environ['SLURM_JOB_ID'],'provider_calls_expected':9,'tasks':rows,'complete':True}
    write_json_atomic(RUN/'seed-completion.json', receipt)
    print(json.dumps(receipt), flush=True)

if __name__ == '__main__': main()
