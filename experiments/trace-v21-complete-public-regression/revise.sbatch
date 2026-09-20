#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-complete-public
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/revise-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/revise-%j.err
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?submit this job from the regression worktree root}"
BUNDLE="$ROOT/experiments/trace-v21-complete-public-regression"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921
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
export BIOMNIBENCH_LIVE_ROOT="$RUN/live"
export XDG_CACHE_HOME="$RUN/cache"
export MPLCONFIGDIR="$RUN/cache/matplotlib"
if [[ -n "${SLURM_TMPDIR:-}" ]] && mkdir -p "$SLURM_TMPDIR" 2>/dev/null; then
  export TMPDIR="$SLURM_TMPDIR"
else
  export TMPDIR="/tmp/aydanh-rtt-complete-public-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
CODEX_SANDBOX_BINARY="$(readlink -f "$(command -v codex-real)")"
CODEX_HELPER_BIN="$TMPDIR/codex-helper-bin"
mkdir -p "$CODEX_HELPER_BIN"
ln -s "$CODEX_SANDBOX_BINARY" "$CODEX_HELPER_BIN/codex-linux-sandbox"
export PATH="$CODEX_HELPER_BIN:$PATH"
mkdir -p "$RUN/logs" "$RUN/live" "$RUN/cache" "$RUN/runtime-coordination"
cd "$ROOT"
exec /home/aydanh/repos/rubric_gen/.venv/bin/rubric-gen revise \
  --experiment "$BUNDLE/configs/da-26-4-rep002.yaml" \
  --max-concurrency 2 \
  --resume
