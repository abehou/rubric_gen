#!/bin/bash
#SBATCH --job-name=rubric-gemini-access
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
export UV_LINK_MODE=copy
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
LOCK_ID=$(sha256sum uv.lock | cut -c1-16)
CHECKOUT_ID=$(printf %s "$PWD" | sha256sum | cut -c1-12)
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-gen-${UID}-${LOCK_ID}-${CHECKOUT_ID}-${SLURM_JOB_ID}"
# Explicit creation avoids the system /usr/local install scheme on some nodes.
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
"$UV_PROJECT_ENVIRONMENT/bin/python" -c 'import os,sys; from pathlib import Path; assert Path(sys.prefix).resolve()==Path(os.environ["UV_PROJECT_ENVIRONMENT"]).resolve()'
uv sync --frozen --python /usr/bin/python3.12
exec "$UV_PROJECT_ENVIRONMENT/bin/python" investigation/babel-overnight-20260907/gemini_access.py
