#!/bin/bash
#SBATCH --job-name=rubric-r20-local-temp
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --exclude=babel-l9-16
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
MAIN_ROOT=/home/aydanh/repos/rubric_gen
cd "$MAIN_ROOT/runs/babel-code/result20-local-temp"
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export UV_LINK_MODE=copy
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
LOCK_ID=$(sha256sum uv.lock | cut -c1-16)
CHECKOUT_ID=$(printf %s "$PWD" | sha256sum | cut -c1-12)
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-gen-${UID}-${LOCK_ID}-${CHECKOUT_ID}-${SLURM_JOB_ID}"
# Explicit creation avoids the system /usr/local install scheme on some nodes.
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
"$UV_PROJECT_ENVIRONMENT/bin/python" -c 'import os,sys; from pathlib import Path; assert Path(sys.prefix).resolve()==Path(os.environ["UV_PROJECT_ENVIRONMENT"]).resolve()'
uv sync --frozen --python /usr/bin/python3.12
# Live workspaces and Codex session state must survive allocation/node changes.
export BIOMNIBENCH_LIVE_ROOT="/home/aydanh/rubric-gen-live/result20"
mkdir -p "$BIOMNIBENCH_LIVE_ROOT"
timeout -k 5 20 "$UV_PROJECT_ENVIRONMENT/bin/python" - <<'CHECK'
import fcntl,os,tempfile
from pathlib import Path
fd,path=tempfile.mkstemp(prefix='recovery-lock-check-',dir='/home/aydanh/repos/rubric_gen/runs')
fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
os.close(fd);Path(path).unlink()
print('Isolated NFS lock acquire/release passed')
CHECK
exec "$UV_PROJECT_ENVIRONMENT/bin/python" "$MAIN_ROOT/investigation/result20-local-temp-recovery-20260908/condition_launch.py" "$@"
