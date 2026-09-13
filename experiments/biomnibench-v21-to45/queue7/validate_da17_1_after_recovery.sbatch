#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=trace-r45-validate-da17-1
#SBATCH --output=experiments/biomnibench-v21-to45/queue7/seed-validate-da17-1-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue7/seed-validate-da17-1-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/trace-results45-inputs-20260912
export RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONPATH="$PWD/src:$PWD/scripts/babel"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export UV_PROJECT_ENVIRONMENT=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602
exec "$UV_PROJECT_ENVIRONMENT/bin/python" experiments/biomnibench-v21-to45/queue8/native_seed_integrity_check.py \
  experiments/biomnibench-v21-to45/queue7/configs/da-17-1.yaml
