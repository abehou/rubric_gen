#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:20:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-r45-archive-da17-1
#SBATCH --output=experiments/biomnibench-v21-to45/queue7/archive-failed-seed4-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue7/archive-failed-seed4-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/trace-results45-inputs-20260912
export PYTHONPATH="$PWD/src:$PWD/scripts/babel"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/biomnibench-v21-to45/queue7/archive_failed_seed_attempt4.py
