#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-evidence-heldout-v2
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/evidence-heldout-v2-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/evidence-heldout-v2-%j.err
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?submit this job from the regression worktree root}"
BUNDLE="$ROOT/experiments/trace-v21-complete-public-regression"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921
set -a
source /home/aydanh/repos/rubric_gen/.env.local
set +a
export PYTHONPATH="$ROOT/src:$BUNDLE"
export RUBRIC_GEN_PROJECT_ROOT="$ROOT"
export RUBRIC_GEN_RUNTIME_CONFIG="$BUNDLE/runtime.json"
export EVIDENCE_POLICY_VERSION=v2
export EVIDENCE_CASE_SCOPE="${EVIDENCE_CASE_SCOPE:-saved}"
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
  export TMPDIR="/tmp/aydanh-rtt-evidence-heldout-v2-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
mkdir -p "$RUN/logs" "$RUN/cache" "$RUN/runtime-coordination"
cd "$ROOT"

# Scheduling-only GPU; the 32-call panel compares saved artifacts and changes no
# revision, solver, selected rubric, or historical audit artifact.
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  "$BUNDLE/run_evidence_calibrated_panel.py"
