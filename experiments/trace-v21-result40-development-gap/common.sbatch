#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
BUNDLE="$ROOT/experiments/trace-v21-result40-development-gap"
RESULT40="$ROOT/experiments/trace-v21-execution-verified-provenance-result40"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921
export RESULT40_CONFIG_BUNDLE=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918/experiments/trace-v21-execution-verified-provenance-result40
export RUBRIC_GEN_PATH_MAP_FILE="$RESULT40/path-map.json"
export RUBRIC_GEN_RUNTIME_CONFIG="$BUNDLE/runtime.json"
export RUBRIC_GEN_PROJECT_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/rtt-result40-development-score-pilot-20260921
export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
if [[ -n "${SLURM_TMPDIR:-}" ]]; then
  export TMPDIR="$SLURM_TMPDIR"
else
  export TMPDIR="/tmp/aydanh-r40-development-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
mkdir -p "$RUN/logs" "$XDG_CACHE_HOME" "$MPLCONFIGDIR"
cd "$ROOT"
