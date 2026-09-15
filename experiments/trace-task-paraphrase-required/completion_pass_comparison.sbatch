#!/bin/bash
# Provider-free exact task/replicate join to clean fixed and completion-parent cells.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --job-name=rtt-pass-compare
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-analysis-20260915/experiments/trace-task-paraphrase-required/completion-pass-comparison-%j.log
set -euo pipefail
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-analysis-20260915
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec "$PY" "$RUN/experiments/trace-task-paraphrase-required/compare_completion_pass_dev3.py"
