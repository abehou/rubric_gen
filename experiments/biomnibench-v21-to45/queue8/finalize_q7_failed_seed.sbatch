#!/bin/bash
# Complete only the already archived, exact da-17-1/rep-003 failed target.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-r45-archive-da17-1-final
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/q7-archive-final-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/q7-archive-final-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  experiments/biomnibench-v21-to45/queue8/finalize_q7_failed_seed.py
