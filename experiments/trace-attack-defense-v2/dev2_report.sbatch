#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-v2-dev3-report1
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v2/dev2-report-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1
REPORT_PYTHON=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
"$REPORT_PYTHON" experiments/trace-attack-defense-v2/dev_report.py dev2
"$REPORT_PYTHON" experiments/trace-attack-defense-v2/dev_integrity.py dev2
"$REPORT_PYTHON" experiments/trace-attack-defense-v2/dev_timing.py dev2
"$REPORT_PYTHON" experiments/trace-attack-defense-v2/dev_costs.py dev3 dev2
"$REPORT_PYTHON" experiments/trace-attack-defense-v2/dev_readiness.py dev2
