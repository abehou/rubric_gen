#!/bin/bash
#SBATCH --job-name=rubric-recovery-tests
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
MAIN_ROOT=$PWD
cd runs/babel-code/result20-current
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-recovery-tests-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
TEST_ROOT="${SLURM_TMPDIR:-/tmp}/rubric-recovery-source-${UID}-${SLURM_JOB_ID}"
mkdir -p "$TEST_ROOT"
cp -a "$MAIN_ROOT/src" "$MAIN_ROOT/tests" "$TEST_ROOT/"
export PYTHONPATH="$TEST_ROOT/src"
cd "$TEST_ROOT"
exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m pytest -q tests/test_submission_revision.py tests/test_submission_revision_artifacts.py tests/test_submission_revision_judge.py
