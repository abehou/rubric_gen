#!/bin/bash
# Fresh native seed/paraphrase input stages; scientific settings come only from YAML.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=256G
#SBATCH --time=08:00:00
#SBATCH --no-requeue
#SBATCH --signal=B:TERM@300
#SBATCH --job-name=trace-clean-input
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/clean-input-%j.log
set -euo pipefail
umask 077
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
ROOT=/home/aydanh/runs/rtt-clean-20260915
CFG=$RUN/experiments/trace-task-paraphrase-required/clean-matched-dev3.yaml
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
STAGE=${1:?stage seed or paraphrase}
case "$STAGE" in seed|paraphrase) LIMIT=4 ;; *) echo "unsupported stage: $STAGE" >&2; exit 2 ;; esac
JOB_ID=$SLURM_JOB_ID
mkdir -p "$ROOT" "$ROOT/logs" "/scratch/job_tmp/$JOB_ID"
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam
export TMPDIR="/scratch/job_tmp/$JOB_ID" XDG_CACHE_HOME="$TMPDIR/xdg-cache"
export UV_CACHE_DIR="$TMPDIR/uv-cache" MPLCONFIGDIR="$TMPDIR/matplotlib"
export BIOMNIBENCH_LIVE_ROOT="$ROOT/live/$JOB_ID"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
mkdir -p "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR" "$BIOMNIBENCH_LIVE_ROOT"
COMMIT=$(git -C "$RUN" rev-parse HEAD)
"$PY" - <<PY
import json
from pathlib import Path
Path("$ROOT/logs/input-$STAGE-$JOB_ID.launch.json").write_text(json.dumps({"job":"$JOB_ID","stage":"$STAGE","commit":"$COMMIT","config":"$CFG","root":"$ROOT","cpus":int("$SLURM_CPUS_PER_TASK"),"time":"$(date -Is)"},indent=2)+"\n")
PY
exec "$PY" -m rubric_gen.cli "$STAGE" --experiment "$CFG" --max-concurrency "$LIMIT"
