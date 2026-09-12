#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-added-heldouts
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/heldouts-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/heldouts-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export TMPDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
mkdir -p "$TMPDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/biomnibench-v21-to45/queue8/prepare_heldouts.py "$@"
