#!/bin/bash
# One real Luna turn on the clean NAS1 path; not a benchmark assignment.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --job-name=trace-clean-smoke
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/clean-smoke-%j.log
set -euo pipefail
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
ROOT=/home/aydanh/runs/rtt-clean-20260915/smoke-$SLURM_JOB_ID
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
mkdir -p "$ROOT" "/scratch/job_tmp/$SLURM_JOB_ID"
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export CODEX_HOME=/home/aydanh/codex-babel/redteam TRACE_CLEAN_SMOKE_ROOT="$ROOT"
export TMPDIR="/scratch/job_tmp/$SLURM_JOB_ID" XDG_CACHE_HOME="$TMPDIR/xdg-cache"
mkdir -p "$XDG_CACHE_HOME"
exec "$PY" "$RUN/experiments/trace-task-paraphrase-required/clean_route_smoke.py"
