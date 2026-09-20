#!/bin/bash
#SBATCH --job-name=r20fb-replay
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=/home/aydanh/runs/r20fb-replay-%j.out
#SBATCH --error=/home/aydanh/runs/r20fb-replay-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-audit3-20260919
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONPATH="$ROOT/src"
cd "$ROOT"
/home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result20-feedback/recover_audit.py \
  publish-saved-opus
