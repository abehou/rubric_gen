#!/bin/bash
# Provider-free preparation of the 16-assignment audit view.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-required-audit-prep
#SBATCH --output=/home/aydanh/runs/trace-task-paraphrase-required-20260914/provisional-audit/prep-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
cd "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONDONTWRITEBYTECODE=1
exec /home/aydanh/repos/rubric_gen/.venv/bin/python experiments/trace-task-paraphrase-required/provisional_prepare_audit.py
