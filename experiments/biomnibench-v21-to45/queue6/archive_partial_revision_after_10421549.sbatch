#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=trace-r30-archive-da1-3
#SBATCH --output=experiments/biomnibench-v21-to45/queue6/archive-da1-3-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue6/archive-da1-3-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src:$PWD/scripts/babel" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/biomnibench-v21-to45/queue6/archive_partial_revision_after_10421549.py
