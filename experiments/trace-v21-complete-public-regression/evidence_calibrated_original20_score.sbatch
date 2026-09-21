#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --array=0-1
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-heldout-old20
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
export EVIDENCE_POLICY_VERSION=v2
export EVIDENCE_CASE_SCOPE=original20
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
export TMPDIR="${SLURM_TMPDIR:-/tmp/aydanh-old20-score-$SLURM_JOB_ID-$SLURM_ARRAY_TASK_ID}"
mkdir -p "$RUN/cache" "$TMPDIR"
cd "$ROOT"

tasks=(
  da-10-1 da-10-3 da-12-2 da-12-4 da-13-1
  da-13-3 da-13-5 da-13-6 da-14-1 da-14-3
  da-14-8 da-15-1 da-15-2 da-15-7 da-15-8
  da-16-1 da-18-5 da-18-7 da-19-1 da-19-6
)
for ((index=SLURM_ARRAY_TASK_ID; index<${#tasks[@]}; index+=2)); do
  task_id="${tasks[$index]}"
  export EVIDENCE_TASK_ID="$task_id"
  for replicate in 1 2 3; do
    export EVIDENCE_REPLICATE="$replicate"
    evidence="$RUN/evidence/$task_id/rep-$(printf '%03d' "$replicate").json"
    export EVIDENCE_INPUT_PATH="$evidence"
    if [[ ! -s "$evidence" ]]; then
      /home/aydanh/repos/rubric_gen/.venv/bin/python \
        "$BUNDLE/extract_original20_evidence.py"
    fi
    /home/aydanh/repos/rubric_gen/.venv/bin/python \
      "$BUNDLE/run_evidence_calibrated_panel.py"
  done
done
