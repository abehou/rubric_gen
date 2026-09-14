#!/bin/bash
# One real current-route request; operational diagnostic, not scientific data.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH --job-name=trace-task-grounded-route
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-task-paraphrase-grounded/route-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam
export TRACE_ROUTE_ROOT=/data/user_data/aydanh/rubric_gen/runs/trace-task-paraphrase-grounded-20260913/route-smoke-${SLURM_JOB_ID}
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-task-paraphrase-grounded-20260913/route-tmp-${SLURM_JOB_ID}
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-task-paraphrase-grounded/route-${SLURM_JOB_ID}
mkdir -p "$TRACE_ROUTE_ROOT" "$TMPDIR" "$XDG_CACHE_HOME"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  experiments/trace-task-paraphrase-grounded/route_smoke.py
