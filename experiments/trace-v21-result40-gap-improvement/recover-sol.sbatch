#!/bin/bash
#SBATCH --job-name=r40-gap-sol-recover
#SBATCH --partition=general
#SBATCH --qos=normal
#SBATCH --gres=gpu:A6000:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/r40-gap-sol-recover-%j.out
#SBATCH --error=/home/aydanh/repos/rubric_gen/runs/r40-gap-sol-recover-%j.err

set -euo pipefail

ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/result40-gap-improvement-20260921
PYTHON=/home/aydanh/repos/rubric_gen/.venv/bin/python
BUNDLE=$ROOT/experiments/trace-v21-result40-gap-improvement

export PYTHONPATH=$ROOT/src
export UV_PROJECT_ENVIRONMENT=/home/aydanh/repos/rubric_gen/.venv

exec "$PYTHON" "$BUNDLE/recover_historical_sol.py" \
  --task "$1" \
  --max-concurrency 60
