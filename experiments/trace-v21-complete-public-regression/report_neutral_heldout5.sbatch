#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:A6000:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-neutral-h5-report
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/neutral-heldout5-report-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-complete-public-regression-20260921/logs/neutral-heldout5-report-%j.err
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?submit this job from the regression worktree root}"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
cd "$ROOT"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-complete-public-regression/report_neutral_heldout5.py
