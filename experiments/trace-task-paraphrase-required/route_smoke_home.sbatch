#!/bin/bash
# One real current-route Codex/Luna request with durable output on NAS1 home.
# This is an operational smoke, not a benchmark assignment.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH --job-name=trace-task-required-route
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-task-paraphrase-required/route-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam
export TRACE_ROUTE_ROOT=/home/aydanh/runs/trace-task-paraphrase-required-20260914/route-smoke-${SLURM_JOB_ID}
export TMPDIR=/scratch/job_tmp/${SLURM_JOB_ID}
export XDG_CACHE_HOME=/home/aydanh/runs/trace-task-paraphrase-required-20260914/cache/route-${SLURM_JOB_ID}
mkdir -p "$TRACE_ROUTE_ROOT" "$TMPDIR" "$XDG_CACHE_HOME"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  experiments/trace-task-paraphrase-grounded/route_smoke.py
