#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=128G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-inputs
#SBATCH --output=experiments/trace-v21-execution-verified-provenance-result40/receipts/input-inspect-%j.out
#SBATCH --error=experiments/trace-v21-execution-verified-provenance-result40/receipts/input-inspect-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$ROOT"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/inspect_inputs.py
