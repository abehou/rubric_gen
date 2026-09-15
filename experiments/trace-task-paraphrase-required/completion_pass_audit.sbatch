#!/bin/bash
# Sol+Opus audit, only after the provider-free candidate completion gate.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --job-name=rtt-pass-audit
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915/experiments/trace-task-paraphrase-required/completion-pass-audit-%j.log
set -euo pipefail
umask 077
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-20260915
ROOT=/home/aydanh/runs/rtt-completion-pass-dev3-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/completion-pass-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
JOB_TMP="/scratch/job_tmp/${SLURM_JOB_ID}"
if ! mkdir -p "$JOB_TMP" 2>/dev/null; then
  JOB_TMP="/tmp/rubric-gen-${SLURM_JOB_ID}"
  mkdir -p "$JOB_TMP"
fi
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CODEX_HOME=/home/aydanh/codex-babel/redteam
export TMPDIR="$JOB_TMP" XDG_CACHE_HOME="$JOB_TMP/xdg-cache"
export UV_CACHE_DIR="$JOB_TMP/uv-cache" MPLCONFIGDIR="$JOB_TMP/matplotlib"
export BIOMNIBENCH_LIVE_ROOT="$ROOT/live/${SLURM_JOB_ID}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
mkdir -p "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT" "$ROOT/logs"
for name in OPENAI_API_KEY ANTHROPIC_API_KEY; do
  value=$("$PY" -c "from dotenv import dotenv_values; import sys; print(dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(sys.argv[1]) or '')" "$name")
  [ -n "$value" ] || { echo "missing $name" >&2; exit 2; }
  export "$name=$value"
done
COMMIT=$(git -C "$RUN" rev-parse HEAD)
"$PY" -c "import json; from pathlib import Path; Path('$ROOT/logs/audit-${SLURM_JOB_ID}.launch.json').write_text(json.dumps({'job':'${SLURM_JOB_ID}','commit':'$COMMIT','config':'$CFG','root':'$ROOT','models':['gpt-5.6-sol','claude-opus-5'],'aggregate_concurrency':8},indent=2)+'\n')"
exec "$PY" -m rubric_gen.cli detect --experiment "$CFG" --max-concurrency 8 --resume
