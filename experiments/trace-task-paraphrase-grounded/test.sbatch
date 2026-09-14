#!/bin/bash
# Provider-free candidate dispatch and focused regression tests.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-task-grounded-tests
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-task-paraphrase-grounded/test-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/tests" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  -m pytest -q tests/test_trace_task_paraphrase_grounded.py tests/test_trace_defense_v21.py tests/test_trace_defense_v2.py
