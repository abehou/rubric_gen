#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-heldout16-v2
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
export EVIDENCE_CASE_SCOPE=new20_remaining16
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
  export TMPDIR="/tmp/aydanh-rtt-heldout16-v2-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
mkdir -p "$RUN/cache" "$ROOT/diagnostics/heldout-judge-failure-analysis"
cd "$ROOT"

tasks=(
  da-8-1 da-20-4 da-19-3 da-4-1 da-1-3 da-3-5 da-4-6 da-5-1
  da-9-7 da-24-3 da-6-5 da-17-3 da-1-4 da-8-3 da-9-1 da-20-1
)
for task_id in "${tasks[@]}"; do
  export EVIDENCE_TASK_ID="$task_id"
  /home/aydanh/repos/rubric_gen/.venv/bin/python \
    "$BUNDLE/extract_heldout_judge_cases.py"
  /home/aydanh/repos/rubric_gen/.venv/bin/python \
    "$BUNDLE/run_evidence_calibrated_panel.py"
done
