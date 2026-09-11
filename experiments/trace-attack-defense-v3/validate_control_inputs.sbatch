#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH --job-name=trace-v3-v21-inputs
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/input-validation-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v3/validate_control_inputs.py
