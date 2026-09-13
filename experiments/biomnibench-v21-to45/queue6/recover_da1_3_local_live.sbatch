#!/bin/bash
# Missing-only native Results30 resume with controller workspaces on node-local
# scratch. The study/output roots, provider identity, and resume semantics stay
# unchanged; this only avoids duplicating the 9 GB task data on quota-exhausted
# NFS while a failed assignment is reconstructed.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --account=dfried
#SBATCH --job-name=trace-r30-da-1-3-local-resume
#SBATCH --output=experiments/biomnibench-v21-to45/queue6/da-1-3-local-resume-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue6/da-1-3-local-resume-%j.err

set -euo pipefail
umask 077
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONPATH="$PWD/src:$PWD/scripts/babel"
export PYTHONPYCACHEPREFIX=/data/user_data/aydanh/rubric_gen/cache/python/runtime-${SLURM_JOB_ID}
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/uv
export UV_PROJECT_ENVIRONMENT=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/xdg
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/matplotlib
export TMPDIR=/tmp/rubric-gen-tmp-${SLURM_JOB_ID}
export BIOMNIBENCH_LIVE_ROOT=/tmp/rubric-gen-live-${SLURM_JOB_ID}
mkdir -p "$TMPDIR" "$BIOMNIBENCH_LIVE_ROOT"
exec "$UV_PROJECT_ENVIRONMENT/bin/python" -m rubric_gen.cli revise \
  --experiment experiments/biomnibench-v21-to45/queue6/configs/da-1-3.yaml \
  --max-concurrency 4 --assignment-workers 4 --resume
