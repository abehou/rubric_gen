#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-v3-unit
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-user-parallel-diagnostics/unit-%j.log
#SBATCH --error=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-user-parallel-diagnostics/unit-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src:$PWD/tests:$PWD/scripts/babel" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
if [ "$#" -eq 0 ]; then
  set -- tests/test_user_feedback_factors.py
fi
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python -m pytest -q "$@"
