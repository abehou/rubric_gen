#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=trace-cleanup-caches-direct
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/cache-clean-direct-v2-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/cache-clean-direct-v2-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
exec /home/aydanh/repos/rubric_gen/.venv/bin/python experiments/biomnibench-v21-to45/queue8/cleanup_exact_runtime_caches_direct.py
