#!/bin/bash
#SBATCH --job-name=cue-active-validate
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/cue-active-validation-%j.out
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/home/aydanh/repos/rubric_gen/runs/babel-code/result20-cue-active-violations/src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
exec /home/aydanh/repos/rubric_gen/.venv/bin/python investigation/result20-cue-active-violations-20260909/validate_inputs.py
