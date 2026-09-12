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
         runtime_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q2-original-20260912
         task_driver=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-task-scope-8c6dfd8.py ;;
 queue3) source_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-feedback-matrix-queue3-20260912
         runtime_root=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-audit-q3-reviewed-20260912
         task_driver=$source_root/experiments/biomnibench-v21-to45/queue3/audit.py ;;
 *) exit 2 ;;
esac
scope=$1
shift
driver_root=${SLURM_SUBMIT_DIR:?}
cd "$source_root"
export RUBRIC_GEN_PROJECT_ROOT="$source_root" PYTHONPATH="$runtime_root/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export TMPDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p "$TMPDIR"
python_bin=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
failed=0
for cell in "$@"; do
  if [ "$scope" = queue2 ]; then
    for task in da-3-4 da-11-1 da-18-1; do
      if ! "$python_bin" "$task_driver" "$cell" "$task"; then failed=1; fi
    done
  else
    if ! "$python_bin" "$task_driver" "$cell"; then failed=1; fi
  fi
done
exit "$failed"
