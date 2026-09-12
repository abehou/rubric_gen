#!/bin/bash
#SBATCH --job-name=trace-v3-forensic
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --output=experiments/trace-attack-defense-v3/forensic-%j.log
#SBATCH --error=experiments/trace-attack-defense-v3/forensic-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
python3 experiments/trace-attack-defense-v3/forensic_user_calibration.py
