#!/bin/bash
#SBATCH --job-name=rubric-results45-data
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=04:00:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
export HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_HUB_DISABLE_PROGRESS_BARS=1
export HF_HOME="${SLURM_TMPDIR:-/tmp}/rubric-hf-${UID}-${SLURM_JOB_ID}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
exec .venv/bin/python investigation/biomnibench-results45-20260908/prepare_data.py
