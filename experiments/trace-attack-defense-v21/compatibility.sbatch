#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-v21-compat
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v21/compatibility-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src"
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v21/compatibility.py --out docs/reports/2026-09-11/trace-attack-defense-v2.1/compatibility-118.json
