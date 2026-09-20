#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
BUNDLE="$ROOT/experiments/trace-v21-execution-verified-provenance-result20-feedback"
RUN=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920
export PYTHONPATH="$ROOT/src"
export RUBRIC_GEN_PROJECT_ROOT="$ROOT"
export RUBRIC_GEN_RUNTIME_CONFIG="$BUNDLE/runtime.json"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/live/rtt-result20-feedback-policies-20260920
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/rtt-result20-feedback-policies-20260920
export UV_CACHE_DIR="$XDG_CACHE_HOME/uv"
export UV_PROJECT_ENVIRONMENT=/home/aydanh/repos/rubric_gen/.venv
export MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
if [[ -n "${SLURM_TMPDIR:-}" ]] && mkdir -p "$SLURM_TMPDIR" 2>/dev/null; then
  export TMPDIR="$SLURM_TMPDIR"
elif mkdir -p "/scratch/job_tmp/$SLURM_JOB_ID" 2>/dev/null; then
  export TMPDIR="/scratch/job_tmp/$SLURM_JOB_ID"
else
  export TMPDIR="/tmp/aydanh-rtt-result20-feedback-$SLURM_JOB_ID"
  mkdir -p "$TMPDIR"
fi
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
