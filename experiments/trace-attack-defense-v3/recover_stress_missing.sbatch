#!/bin/bash
# Missing-only recovery for failed job 10402416; no scientific changes.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
#SBATCH --mem=512G
#SBATCH --time=12:00:00
#SBATCH --job-name=trace-v3-stress-recovery
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/stress-recovery-%j.log
#SBATCH --error=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/stress-recovery-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v3/recover_stress_missing.py
