#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=8
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-q2-audit
#SBATCH --output=experiments/biomnibench-v21-to45/queue2/audit-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue2/audit-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export TMPDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}
mkdir -p "$TMPDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/biomnibench-v21-to45/queue2/audit.py "$@"
