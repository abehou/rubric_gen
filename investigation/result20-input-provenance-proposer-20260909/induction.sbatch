#!/bin/bash
#SBATCH --job-name=rubric-proposer-test
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=128G
#SBATCH --time=01:00:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
TASK_ARM=cue
CODE_ROOT="$PWD/runs/babel-code/result20-input-provenance-proposer"
MAIN_ROOT=$PWD
export PYTHONPATH="$CODE_ROOT/src" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-evidence-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
cd "$CODE_ROOT"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
"$UV_PROJECT_ENVIRONMENT/bin/python" -m pytest tests/test_rubric_evolution.py -q
exec "$UV_PROJECT_ENVIRONMENT/bin/python" "$MAIN_ROOT/investigation/result20-input-provenance-proposer-20260909/induction.py"
