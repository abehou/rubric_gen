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
#SBATCH --job-name=rtt-neutral-heldout5
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/neutral-heldout5-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/neutral-heldout5-%j.err
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
  export TMPDIR="/tmp/aydanh-rtt-neutral-heldout5-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
mkdir -p "$RUN/logs" "$RUN/cache" "$RUN/runtime-coordination"
cd "$ROOT"

# The A6000 is scheduling-only. This API workload uses 8 CPU / 32 GiB and
# reads four completed artifacts without restarting any revision.
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  "$BUNDLE/run_neutral_heldout5.py"
