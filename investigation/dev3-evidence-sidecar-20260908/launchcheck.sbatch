#!/bin/bash
#SBATCH --job-name=rubric-evidence-launchcheck
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
TASK_ARM=${1:?control or evidence}
case "$TASK_ARM" in
 control) CODE_ROOT="$PWD/runs/babel-code/dev3-evidence-control";;
 evidence) CODE_ROOT="$PWD/runs/babel-code/dev3-evidence-sidecar";;
 *) exit 2;;
esac
MAIN_ROOT=$PWD
export PYTHONPATH="$CODE_ROOT/src" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-evidence-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
cd "$CODE_ROOT"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m pytest -q "$MAIN_ROOT/investigation/dev3-evidence-sidecar-20260908/test_launcher.py" tests/test_babel_stage_recovery.py tests/test_runtime_capacity.py tests/test_babel_launcher.py
