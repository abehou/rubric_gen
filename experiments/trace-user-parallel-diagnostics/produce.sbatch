#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
#SBATCH --mem=512G
#SBATCH --time=2-00:00:00
#SBATCH --job-name=trace-user-factors
#SBATCH --output=experiments/trace-user-parallel-diagnostics/producer-%j.log
#SBATCH --error=experiments/trace-user-parallel-diagnostics/producer-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
FACTOR_PYTHON=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
export OPENAI_API_KEY="$($FACTOR_PYTHON -c 'from dotenv import dotenv_values; print(dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")["OPENAI_API_KEY"])')"
# One process/assignment at a time per cell, three cells concurrently, all
# through the SAME checked-in global 60-provider/one-audit coordinator.
# Arguments are the cells approved after the fixed feedback diagnostic review.
if [ "$#" -eq 0 ]; then
  echo 'Pass explicitly reviewed C10 C01 C11 cells; this script does not choose a winner.' >&2
  exit 2
fi
run_cell() {
  local cell="$1" status=0
  case "$cell" in C10|C01|C11) ;; *) return 2;; esac
  for task in da-3-4 da-11-1 da-18-1; do
    if "$FACTOR_PYTHON" -m rubric_gen.cli revise \
      --experiment "experiments/trace-user-parallel-diagnostics/configs/$cell/$task.yaml" \
      --assignment-workers 1 --max-concurrency 1 --resume; then :; else status=1; fi
  done
  return "$status"
}
pids=()
for cell in "$@"; do
  run_cell "$cell" &
  pids+=("$!")
done
status=0
for pid in "${pids[@]}"; do
  if wait "$pid"; then :; else status=1; fi
done
exit "$status"
