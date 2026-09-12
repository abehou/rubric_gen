#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-reviewed-audit
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/audit-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/audit-%j.err
set -euo pipefail
case "${1:?queue2 or queue3}" in
 queue2) source_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-appendix-queue2-20260912
         runtime_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q2-original-20260912 ;;
 queue3) source_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-feedback-matrix-queue3-20260912
         runtime_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q3-reviewed-20260912 ;;
 *) exit 2 ;;
esac
scope=$1
shift
cd "$source_root"
export RUBRIC_GEN_PROJECT_ROOT="$source_root" PYTHONPATH="$runtime_root/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export TMPDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p "$TMPDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python "$source_root/experiments/biomnibench-v21-to45/$scope/audit.py" "$@"
