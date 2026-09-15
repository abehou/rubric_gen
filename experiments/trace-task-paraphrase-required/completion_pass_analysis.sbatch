#!/bin/bash
# Provider-free derived tables after the candidate Sol+Opus audit completes.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --job-name=rtt-pass-analysis
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-analysis-20260915/experiments/trace-task-paraphrase-required/completion-pass-analysis-%j.log
set -euo pipefail
RUN=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-dev3-next-analysis-20260915
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
export RUBRIC_GEN_PROJECT_ROOT="$RUN" PYTHONPATH="$RUN/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec "$PY" "$RUN/experiments/trace-task-paraphrase-required/analyze_completion_pass_dev3.py"
