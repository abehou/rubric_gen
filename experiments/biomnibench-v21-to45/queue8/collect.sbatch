#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-reviewed-collector
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/collect-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/collect-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python "$1" "$2"
