#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
BUNDLE="$ROOT/experiments/trace-v21-execution-verified-provenance-result40"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918
export RESULT40_CONFIG_BUNDLE=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918/experiments/trace-v21-execution-verified-provenance-result40
export RUBRIC_GEN_PATH_MAP_FILE="$BUNDLE/path-map.json"
export PYTHONPATH="$ROOT/src"
export RUBRIC_GEN_PROJECT_ROOT="$ROOT"
export RUBRIC_GEN_RUNTIME_CONFIG="$BUNDLE/runtime.json"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/live/rtt-result40-expansion-20260918
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/rtt-result40-expansion-20260918
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/rtt-result40-expansion-20260918/uv
export UV_PROJECT_ENVIRONMENT=/home/aydanh/repos/rubric_gen/.venv
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/rtt-result40-expansion-20260918/matplotlib
if [[ -n "${SLURM_TMPDIR:-}" ]] && mkdir -p "$SLURM_TMPDIR" 2>/dev/null; then
  export TMPDIR="$SLURM_TMPDIR"
elif mkdir -p "/scratch/job_tmp/$SLURM_JOB_ID" 2>/dev/null; then
  export TMPDIR="/scratch/job_tmp/$SLURM_JOB_ID"
else
  export TMPDIR="/tmp/aydanh-rtt-result40-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
# Codex CLI 0.154 invokes its Linux sandbox through this argv[0] alias.  Babel's
# account wrapper intentionally exposes only `codex`/`codex-real`, so create the
# disposable alias inside this job rather than mutating the shared installation.
CODEX_SANDBOX_BINARY="$(readlink -f "$(command -v codex-real)")"
if [[ ! -x "$CODEX_SANDBOX_BINARY" ]]; then
  echo "Codex Linux sandbox binary is unavailable: $CODEX_SANDBOX_BINARY" >&2
  exit 1
fi
CODEX_HELPER_BIN="$TMPDIR/codex-helper-bin"
mkdir -p "$CODEX_HELPER_BIN"
ln -s "$CODEX_SANDBOX_BINARY" "$CODEX_HELPER_BIN/codex-linux-sandbox"
export PATH="$CODEX_HELPER_BIN:$PATH"
mkdir -p "$RUN/logs" "$BIOMNIBENCH_LIVE_ROOT" "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR"
cd "$ROOT"
