#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-public-firewall
#SBATCH --output=experiments/trace-user-public-evidence-firewall/feedback-%j.log
#SBATCH --error=experiments/trace-user-public-evidence-firewall/feedback-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-user-public-evidence-firewall/run_feedback_checks.py
