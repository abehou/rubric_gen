#!/bin/bash
#SBATCH --job-name=baseline-checkpoint
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/slurm-%x-%j.out
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/caches/matplotlib-baseline-freeze
exec /home/aydanh/repos/rubric_gen/.venv/bin/python scripts/reporting/frozen_biomnibench.py
