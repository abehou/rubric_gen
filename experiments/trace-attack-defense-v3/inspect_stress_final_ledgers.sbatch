#!/bin/bash
# Provider-free inspection of the stress ledger after missing-only recovery.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:20:00
#SBATCH --job-name=trace-v3-ledger-inspect
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/ledger-inspect-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src:$ROOT/experiments/trace-attack-defense-v3" PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v3/inspect_stress_final_ledgers.py
