#!/bin/bash
# Native clean-run outcome audit; invoked only after revision completion gate.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --job-name=trace-clean-audit
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/clean-audit-%j.log
set -euo pipefail
umask 077
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
ROOT=/home/aydanh/runs/rtt-clean-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/clean-matched-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
JOB_ID=$SLURM_JOB_ID
mkdir -p "$ROOT" "$ROOT/logs" "/scratch/job_tmp/$JOB_ID"
export RUBRIC_GEN_PROJECT_ROOT="$RUN"
export PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam
export TMPDIR="/scratch/job_tmp/$JOB_ID"
export XDG_CACHE_HOME="$TMPDIR/xdg-cache"
export UV_CACHE_DIR="$TMPDIR/uv-cache"
export MPLCONFIGDIR="$TMPDIR/matplotlib"
export BIOMNIBENCH_LIVE_ROOT="$ROOT/live/$JOB_ID"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
mkdir -p "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT"
for name in OPENAI_API_KEY ANTHROPIC_API_KEY; do
  value=$("$PY" -c "from dotenv import dotenv_values; import sys; v=dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(sys.argv[1]); print(v or '')" "$name")
  [ -n "$value" ] || { echo "missing $name" >&2; exit 2; }
  export "$name=$value"
done
COMMIT=$(git -C "$RUN" rev-parse HEAD)
"$PY" - <<PY
import json
from pathlib import Path
Path("$ROOT/logs/audit-$JOB_ID.launch.json").write_text(json.dumps({"job":"$JOB_ID","commit":"$COMMIT","config":"$CFG","root":"$ROOT","cpus":int("$SLURM_CPUS_PER_TASK"),"models":["gpt-5.6-sol","claude-opus-5"],"time":"$(date -Is)"},indent=2)+"\\n")
PY
exec "$PY" -m rubric_gen.cli detect --experiment "$CFG" --max-concurrency 8 --resume
