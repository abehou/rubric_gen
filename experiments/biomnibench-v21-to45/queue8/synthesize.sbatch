#!/bin/bash
# Provider-free final/interim synthesis of persisted Queue2/3/scale records.
# Native audits own all model calls; this stage only reconstructs reports.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-scale-synthesis
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/synthesis-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/synthesis-%j.err

set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
export PYTHONPATH="$PWD/src:$PWD/scripts/babel"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TMPDIR="/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}"
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/xdg
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/matplotlib
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$MPLCONFIGDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  experiments/biomnibench-v21-to45/queue8/synthesize.py
