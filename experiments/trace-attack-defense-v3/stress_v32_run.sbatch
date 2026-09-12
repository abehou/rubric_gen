#!/bin/bash
# Third and final User delivery iteration. Three native scoped revisions;
# one assignment worker per task, matching the preceding stress runner.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=512G
#SBATCH --time=2-00:00:00
#SBATCH --job-name=trace-v32-stress
#SBATCH --open-mode=append
#SBATCH --output=experiments/trace-attack-defense-v3/stress-v32-%j.log
#SBATCH --error=experiments/trace-attack-defense-v3/stress-v32-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the committed source checkout}"
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
V32_PYTHON=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
export OPENAI_API_KEY="$($V32_PYTHON -c 'from dotenv import dotenv_values; print(dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")["OPENAI_API_KEY"])')"
printf 'Job %s; restart %s; commit ' "$SLURM_JOB_ID" "${SLURM_RESTART_COUNT:-0}"
git rev-parse HEAD
pids=()
for task in da-15-1 da-13-6 da-18-5; do
  "$V32_PYTHON" -m rubric_gen.cli revise \
    --experiment "experiments/trace-attack-defense-v3/stress-v32/v32-candidate-${task}.yaml" \
    --assignment-workers 1 --max-concurrency 1 --resume &
  pids+=("$!")
done
result=0
for pid in "${pids[@]}"; do
  if wait "$pid"; then :; else result=1; fi
done
exit "$result"
