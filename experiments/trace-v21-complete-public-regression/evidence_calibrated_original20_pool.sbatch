#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-heldout-old20-pool
set -euo pipefail

ROOT="${SLURM_SUBMIT_DIR:?submit from the evidence-policy worktree root}"
BUNDLE="$ROOT/experiments/trace-v21-complete-public-regression"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/evidence-calibrated-original20-v2
set -a
source /home/aydanh/repos/rubric_gen/.env.local
set +a
export PATH="/home/aydanh/repos/rubric_gen/.venv/bin:$PATH"
export PYTHONPATH="$ROOT/src:$BUNDLE"
export RUBRIC_GEN_PROJECT_ROOT="$ROOT"
export RUBRIC_GEN_RUNTIME_CONFIG="$BUNDLE/runtime.json"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export XDG_CACHE_HOME="$RUN/cache"
export MPLCONFIGDIR="$RUN/cache/matplotlib"
export TMPDIR="${SLURM_TMPDIR:-/tmp/aydanh-old20-pool-$SLURM_JOB_ID}"
mkdir -p "$RUN/cache" "$TMPDIR"
cd "$ROOT"
/home/aydanh/repos/rubric_gen/.venv/bin/python \
  "$BUNDLE/prepare_original20_neutral_pool.py"
