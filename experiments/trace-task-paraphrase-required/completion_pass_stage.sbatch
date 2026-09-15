#!/bin/bash
# Frozen 18-assignment completion-pass RTT Dev3 revision.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --job-name=rtt-pass-dev3
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915/experiments/trace-task-paraphrase-required/completion-pass-stage-%j.log
set -euo pipefail
umask 077
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915
ROOT=/home/aydanh/runs/rtt-completion-pass-dev3-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/completion-pass-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
mkdir -p "$ROOT" "$ROOT/logs"
JOB_TMP="/scratch/job_tmp/${SLURM_JOB_ID}"
if ! mkdir -p "$JOB_TMP" 2>/dev/null; then
  JOB_TMP="/tmp/rubric-gen-${SLURM_JOB_ID}"
  mkdir -p "$JOB_TMP"
fi
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam
export TMPDIR="$JOB_TMP" XDG_CACHE_HOME="$JOB_TMP/xdg-cache"
export UV_CACHE_DIR="$JOB_TMP/uv-cache" MPLCONFIGDIR="$JOB_TMP/matplotlib"
export BIOMNIBENCH_LIVE_ROOT="$ROOT/live/${SLURM_JOB_ID}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
mkdir -p "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT"
if [ -z "${OPENAI_API_KEY:-}" ]; then
  OPENAI_API_KEY=$("$PY" -c "from dotenv import dotenv_values; print(dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get('OPENAI_API_KEY') or '')")
  [ -n "$OPENAI_API_KEY" ] || { echo 'OPENAI_API_KEY unavailable' >&2; exit 2; }
  export OPENAI_API_KEY
fi
COMMIT=$(git -C "$RUN" rev-parse HEAD)
"$PY" -c "import json; from pathlib import Path; Path('$ROOT/logs/revise-${SLURM_JOB_ID}.launch.json').write_text(json.dumps({'job':'${SLURM_JOB_ID}','commit':'$COMMIT','config':'$CFG','root':'$ROOT','expected_assignments':18,'aggregate_concurrency':12,'assignment_workers':8},indent=2)+'\n')"
exec "$PY" -m rubric_gen.cli revise --experiment "$CFG" --max-concurrency 12 --assignment-workers 8 --resume
