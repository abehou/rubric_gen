#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-g1
#SBATCH --output=experiments/trace-v21-execution-verified-provenance-result40/receipts/g1-inspect-%j.out
#SBATCH --error=experiments/trace-v21-execution-verified-provenance-result40/receipts/g1-inspect-%j.err
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918
export PYTHONPATH="$ROOT/src"
cd "$ROOT"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/inspect_sources.py
