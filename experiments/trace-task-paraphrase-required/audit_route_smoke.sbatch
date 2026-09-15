#!/bin/bash
# One tiny same-route request per audit model; operational gate only.
#SBATCH --account=dfried
#SBATCH --partition=general
#SBATCH --qos=normal
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:15:00
#SBATCH --job-name=trace-audit-smoke
#SBATCH --output=/home/aydanh/runs/trace-task-paraphrase-required-20260914/provisional-audit/route-smoke-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
cd "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export TMPDIR=/scratch/job_tmp/${SLURM_JOB_ID}
mkdir -p "$TMPDIR"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-task-paraphrase-required/audit_route_smoke.py
