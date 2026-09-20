#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:A6000:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-heldout5-da264
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/heldout5-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/heldout5-%j.err
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?submit this job from the regression worktree root}"
BUNDLE="$ROOT/experiments/trace-v21-complete-public-regression"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921
set -a
source /home/aydanh/repos/rubric_gen/.env.local
set +a
export PYTHONPATH="$ROOT/src"
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
if [[ -n "${SLURM_TMPDIR:-}" ]] && mkdir -p "$SLURM_TMPDIR" 2>/dev/null; then
  export TMPDIR="$SLURM_TMPDIR"
else
  export TMPDIR="/tmp/aydanh-rtt-heldout5-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
mkdir -p "$RUN/logs" "$RUN/cache" "$RUN/runtime-coordination"
cd "$ROOT"

# The reserved A6000 is used only to obtain a general-partition node; this API
# workload uses the requested CPU and memory resources. Complete the missing
# Gemini panel for the two repaired artifacts, then run only the two new
# heldout rubrics against the four saved final artifacts.
/home/aydanh/repos/rubric_gen/.venv/bin/python "$BUNDLE/run_gemini_audit.py"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python "$BUNDLE/run_heldout5.py"
