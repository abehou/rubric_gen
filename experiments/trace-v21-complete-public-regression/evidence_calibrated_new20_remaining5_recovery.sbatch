#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-heldout5-recovery64
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
  export TMPDIR="/tmp/aydanh-rtt-heldout5-recovery-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
mkdir -p "$RUN/cache" "$ROOT/diagnostics/heldout-judge-failure-analysis"
cd "$ROOT"

tasks=(da-17-3 da-1-4 da-8-3 da-9-1 da-20-1)
for task_id in "${tasks[@]}"; do
  export EVIDENCE_TASK_ID="$task_id"
  for replicate in 1 2 3; do
    export EVIDENCE_REPLICATE="$replicate"
    evidence="$ROOT/diagnostics/heldout-judge-failure-analysis/new20-remaining16-${task_id}-rep$(printf '%03d' "$replicate")-evidence.json"
    if [[ ! -s "$evidence" ]]; then
      /home/aydanh/repos/rubric_gen/.venv/bin/python \
        "$BUNDLE/extract_heldout_judge_cases.py"
    fi
    /home/aydanh/repos/rubric_gen/.venv/bin/python \
      "$BUNDLE/run_evidence_calibrated_panel.py"
  done
done
