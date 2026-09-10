#!/bin/bash
#SBATCH --job-name=rubric-capacity-v2-tests
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
cd runs/babel-code/result20-capacity-v2
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-capacity-v2-tests-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
"$UV_PROJECT_ENVIRONMENT/bin/python" -m pytest tests/test_rubric_evolution.py tests/test_runtime_capacity.py tests/test_rubric_generation.py tests/test_pretreatment_reuse.py tests/test_red_team.py -q --basetemp="${SLURM_TMPDIR:-/tmp}/rubric-validation-pytest-${SLURM_JOB_ID}"
