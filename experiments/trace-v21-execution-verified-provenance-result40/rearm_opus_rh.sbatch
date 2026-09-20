#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:30:00
#SBATCH --gres=gpu:1
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-opus-rh-rearm
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/opus-rh-rearm-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/opus-rh-rearm-%j.err
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?Slurm submit directory is required}"
export PYTHONPATH="$ROOT/src:$ROOT/experiments/trace-v21-execution-verified-provenance-result40"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RESULT40_SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
cd "$ROOT"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/rearm_opus_rh.py
