#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --job-name=attack-defense-readiness
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v1/experiments/trace-attack-defense-v1/readiness-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v1
export PYTHONPATH="$PWD/src"
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v1/uv
mkdir -p "$UV_CACHE_DIR"
/home/aydanh/tools/uv/uv lock --check --offline
/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v1/prepare.py
/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python - <<'PY'
import sys,json,os
from pathlib import Path
sys.path.insert(0,'experiments/trace-attack-defense-v1')
import run,prepare,jsonschema
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.runtime.capacity import policy
from rubric_gen.artifacts.serialization import write_json_atomic
exp=load_experiment(Path('experiments/trace-attack-defense-v1/result20.yaml'))
assert tuple(exp.outcome_audit['models'])==run.PANEL
assert len(run.smoke_assignments(exp))==2
sources=run.install_reuse()  # Exact native request reuse setup, no provider calls.
for path in sources:
 assert Path(path).is_dir(),path
result={'success':True,'provider_calls':0,'job':os.environ['SLURM_JOB_ID'],'python':sys.version,
        'executable':sys.executable,'experiment_id':exp.experiment_id,'smoke_assignments':run.smoke_assignments(exp),
        'runtime':policy(),'shared_mount':run.check_shared_mount(),'auditors':list(run.PANEL),'reuse_sources':sources,
        'jsonschema':jsonschema.__file__}
write_json_atomic(Path('experiments/trace-attack-defense-v1/receipts/readiness.json'),result)
print(json.dumps(result),flush=True)
PY
