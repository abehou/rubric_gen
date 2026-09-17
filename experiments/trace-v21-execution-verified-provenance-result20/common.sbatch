#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-v21-result20-20260917
BUNDLE="$ROOT/experiments/trace-v21-execution-verified-provenance-result20"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next
export PYTHONPATH="$ROOT/src"
export RUBRIC_GEN_PROJECT_ROOT="$ROOT"
export RUBRIC_GEN_RUNTIME_CONFIG="$BUNDLE/runtime.json"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/live/rtt-result20-next
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/rtt-result20-next
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/rtt-result20-next/uv
export UV_PROJECT_ENVIRONMENT=/home/aydanh/repos/rubric_gen/.venv
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/rtt-result20-next/matplotlib
export TMPDIR="/scratch/job_tmp/$SLURM_JOB_ID"
mkdir -p "$RUN/logs" "$BIOMNIBENCH_LIVE_ROOT" "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR" "$TMPDIR"
cd "$ROOT"
