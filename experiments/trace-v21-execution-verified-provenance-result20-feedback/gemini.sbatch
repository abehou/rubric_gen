#!/bin/bash
#SBATCH --job-name=r20fb-gemini
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --output=/home/aydanh/runs/r20fb-gemini-%j.out
#SBATCH --error=/home/aydanh/runs/r20fb-gemini-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-audit3-20260919
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export RUBRIC_GEN_AGGREGATE_CONCURRENCY=60
export RUBRIC_GEN_AUDIT_STUDIES=3
export RUBRIC_GEN_AUDIT_OPENAI_CONCURRENCY=60
export RUBRIC_GEN_AUDIT_ANTHROPIC_CONCURRENCY=60
export RUBRIC_GEN_AUDIT_GOOGLE_CONCURRENCY=60
export PYTHONPATH="$ROOT/src"
cd "$ROOT"
/home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result20-feedback/recover_audit.py \
  gemini
