#!/bin/bash
# Remove only the two allowlisted obsolete cache environments.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-cleanup-caches-final
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/cache-clean-final-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/cache-clean-final-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  experiments/biomnibench-v21-to45/queue8/cleanup_exact_runtime_caches.py
