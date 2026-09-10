#!/bin/bash
#SBATCH --job-name=cue-active-delivery
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/cue-active-delivery-%j.out
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/aydanh/repos/rubric_gen/runs/babel-code/result20-cue-active-violations/src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
exec /home/aydanh/repos/rubric_gen/.venv/bin/python investigation/result20-cue-pair-recovery-20260909/delivery.py
