#!/bin/bash
# Provider-free validation/finalization of the recovered scoped stress cohort.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-v3-recovery-finalize
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/finalize-recovery-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/experiments/trace-attack-defense-v3" PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v3/finalize_stress_recovery.py
