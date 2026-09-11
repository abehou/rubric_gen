#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-v3-unit
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/unit-%j.log
#SBATCH --error=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/unit-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python -m unittest -v tests/test_user_delivery_v3.py
