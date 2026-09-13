#!/bin/bash
# Run the native detect command for the fixed Results30/45 scale cells.
# This is a serial audit owner: native --resume preserves completed judgments,
# and the existing audit lease/provider cap remain authoritative.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-scale-audit
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/scale-audit-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/scale-audit-%j.err

set -euo pipefail

scope=${1:?expected results30 or results45}
python_bin=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
q6_source=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
q7_source=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-results45-inputs-20260912

run_detect() {
  local source=$1
  local config=$2
  local label=$3
  cd "$source"
  export RUBRIC_GEN_PROJECT_ROOT="$source"
  export PYTHONPATH="$source/src:$source/scripts/babel"
  export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
  export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
  export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
  export TMPDIR="/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}"
  export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/xdg
  export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/matplotlib
  export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/live/runtime-throughput
  mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT"
  echo "$(date --iso-8601=seconds) detect $label $config source=$source" >&2
  "$python_bin" scripts/babel/experiment.py --profile dev3-4 detect \
    --experiment "$config" --resume
}

failed=0
case "$scope" in
  results30)
    for task in da-1-3 da-19-3 da-20-4 da-26-2 da-26-4 da-3-5 da-4-1 da-4-6 da-5-1 da-8-1; do
      config="$q6_source/experiments/biomnibench-v21-to45/queue6/configs/$task.yaml"
      if ! run_detect "$q6_source" "$config" "results30/$task"; then failed=1; fi
    done
    ;;
  results45)
    for task in da-1-4 da-17-1 da-17-3 da-17-5 da-19-4 da-20-1 da-24-3 da-25-1 da-4-7 da-6-2 da-6-5 da-8-2 da-8-3 da-9-1 da-9-7; do
      config="$q7_source/experiments/biomnibench-v21-to45/queue7/configs/$task.yaml"
      if ! run_detect "$q7_source" "$config" "results45/$task"; then failed=1; fi
    done
    ;;
  *)
    echo "invalid scope: $scope" >&2
    exit 2
    ;;
esac
exit "$failed"
