#!/usr/bin/env bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --job-name=rtt-r40-inv
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918/experiments/trace-v21-execution-verified-provenance-result40/receipts/inventory-%j.out
#SBATCH --error=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918/experiments/trace-v21-execution-verified-provenance-result40/receipts/inventory-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918
cd "$ROOT"
df -hT /data/user_data/aydanh
df -i /data/user_data/aydanh
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
/home/aydanh/repos/rubric_gen/.venv/bin/python experiments/trace-v21-execution-verified-provenance-result40/initial_inventory.py
