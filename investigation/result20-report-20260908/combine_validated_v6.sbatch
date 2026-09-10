#!/bin/bash
#SBATCH --job-name=rubric-r20-validated-merge
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
MAIN_ROOT=$PWD
CODE_ROOT="$MAIN_ROOT/runs/babel-code/result20-checkpoint-recovery"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$CODE_ROOT/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-static-report-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
cd "$CODE_ROOT"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
cd "$MAIN_ROOT"
exec "$UV_PROJECT_ENVIRONMENT/bin/python" "$MAIN_ROOT/investigation/result20-report-20260908/combine_validated_v6.py" "$@"
