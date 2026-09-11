#!/bin/bash
#SBATCH --job-name=trace-v3-stress
#SBATCH --partition=general
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --time=2-00:00:00
#SBATCH --output=experiments/trace-attack-defense-v3/stress-%j.log
#SBATCH --error=experiments/trace-attack-defense-v3/stress-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
ENV=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export PYTHONUNBUFFERED=1
exec "$ENV/bin/python" experiments/trace-attack-defense-v3/stress_pair_run.py
