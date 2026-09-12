#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --job-name=trace-mission-inventory
#SBATCH --output=experiments/biomnibench-v21-to45/inventory-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/inventory-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export PYTHONDONTWRITEBYTECODE=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/biomnibench-v21-to45/inventory.py
