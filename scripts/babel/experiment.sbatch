#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
cd "${SLURM_SUBMIT_DIR:?Submit from the pinned source checkout}"
export RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONPATH="$PWD/src:$PWD/scripts/babel"
export PYTHONPYCACHEPREFIX=/data/user_data/aydanh/rubric_gen/cache/python/runtime-${SLURM_JOB_ID}
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/uv
export UV_PROJECT_ENVIRONMENT=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/xdg
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/matplotlib
export TMPDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-${SLURM_JOB_ID}
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/live/runtime-throughput
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT"
exec "$UV_PROJECT_ENVIRONMENT/bin/python" scripts/babel/experiment.py "$@"
