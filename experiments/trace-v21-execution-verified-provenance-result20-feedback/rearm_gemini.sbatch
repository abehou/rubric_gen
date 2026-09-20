#!/bin/bash
#SBATCH --job-name=r20fb-gem-rearm
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=/home/aydanh/runs/r20fb-gem-rearm-%j.out
#SBATCH --error=/home/aydanh/runs/r20fb-gem-rearm-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-audit3-20260919
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONPATH="$ROOT/src:$ROOT/experiments/trace-v21-execution-verified-provenance-result20-feedback"
export RESULT20_FEEDBACK_SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
cd "$ROOT"
/home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result20-feedback/rearm_gemini.py
