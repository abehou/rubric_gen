#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=48:00:00
#SBATCH --job-name=trace-attack-defense-v1
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v1/experiments/trace-attack-defense-v1/production-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v1
export PYTHONPATH="$PWD/src"
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910/live
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910/tmp
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v1
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v1/uv
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v1/matplotlib
mkdir -p "$TMPDIR" "$BIOMNIBENCH_LIVE_ROOT" "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v1/run.py "${1:-execute}"
