#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=24:00:00
#SBATCH --job-name=trace-v3-v21-control
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/control-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21/live
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21/tmp
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v3/control-v21-compatible
export TRACE_V3_CONTROL_FLAVOR=control-v21-compatible
export UV_CACHE_DIR="$XDG_CACHE_HOME/uv" MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
mkdir -p "$TMPDIR" "$BIOMNIBENCH_LIVE_ROOT" "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v3/control_run.py
