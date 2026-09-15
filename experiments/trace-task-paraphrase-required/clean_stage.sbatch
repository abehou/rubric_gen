#!/bin/bash
# Native fresh clean-run stage wrapper. Scientific settings come only from YAML.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --job-name=trace-clean-stage
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/clean-stage-%j.log
set -euo pipefail
umask 077
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
ROOT=/home/aydanh/runs/rtt-clean-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/clean-matched-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
STAGE=${1:?stage seed|paraphrase|revise}
case "$STAGE" in
  seed|paraphrase) LIMIT=4 ;;
  revise) LIMIT=8 ;;
  *) echo "unsupported stage: $STAGE" >&2; exit 2 ;;
esac
mkdir -p "$ROOT" "$ROOT/logs"
JOB_TMP="/scratch/job_tmp/${SLURM_JOB_ID}"
if ! mkdir -p "$JOB_TMP" 2>/dev/null; then
  JOB_TMP="/tmp/rubric-gen-${SLURM_JOB_ID}"
  mkdir -p "$JOB_TMP"
fi
export RUBRIC_GEN_PROJECT_ROOT="$RUN"
export PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam
export TMPDIR="$JOB_TMP"
export XDG_CACHE_HOME="$TMPDIR/xdg-cache"
export UV_CACHE_DIR="$TMPDIR/uv-cache"
export MPLCONFIGDIR="$TMPDIR/matplotlib"
export BIOMNIBENCH_LIVE_ROOT="$ROOT/live/${SLURM_JOB_ID}"
if [ "$STAGE" = revise ] && [ -z "${OPENAI_API_KEY:-}" ]; then
  OPENAI_API_KEY=$("$PY" -c "from dotenv import dotenv_values; import sys; print(dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get(sys.argv[1]) or '')" OPENAI_API_KEY)
  [ -n "$OPENAI_API_KEY" ] || { echo 'OPENAI_API_KEY unavailable for revise stage' >&2; exit 2; }
  export OPENAI_API_KEY
fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
mkdir -p "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT"
COMMIT=$(git -C "$RUN" rev-parse HEAD)
"$PY" - <<PY
import json
from pathlib import Path
Path("$ROOT/logs/stage-${STAGE}-${SLURM_JOB_ID}.launch.json").write_text(json.dumps({"job":"$SLURM_JOB_ID","stage":"$STAGE","commit":"$COMMIT","config":"$CFG","root":"$ROOT","cpus":int("$SLURM_CPUS_PER_TASK"),"time":"$(date -Is)"},indent=2)+"\n")
PY
if [ "$STAGE" = revise ]; then
  exec "$PY" -m rubric_gen.cli revise --experiment "$CFG" --max-concurrency "$LIMIT" --assignment-workers 8 --resume
else
  exec "$PY" -m rubric_gen.cli "$STAGE" --experiment "$CFG" --max-concurrency "$LIMIT"
fi
