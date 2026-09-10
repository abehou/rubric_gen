#!/bin/bash
#SBATCH --job-name=rubric-env-check
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/src"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-gen-env-check-${UID}-${SLURM_JOB_ID}"
export UV_LINK_MODE=copy
hostname
uv --version
/usr/bin/python3.12 - <<'PY'
import json,sys,sysconfig,os
print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,version=sys.version,paths=sysconfig.get_paths(),environment={k:os.environ.get(k) for k in ['UV_PROJECT_ENVIRONMENT','UV_SYSTEM_PYTHON','UV_TARGET','UV_PREFIX','PYTHONHOME','VIRTUAL_ENV','CONDA_PREFIX']})))
PY
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
"$UV_PROJECT_ENVIRONMENT/bin/python" - <<'PY'
import json,sys,sysconfig
print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,version=sys.version,paths=sysconfig.get_paths())))
PY
uv sync --frozen --python /usr/bin/python3.12
"$UV_PROJECT_ENVIRONMENT/bin/python" -c 'import openai,anthropic,openai_codex; print("frozen provider imports passed; no requests")'
