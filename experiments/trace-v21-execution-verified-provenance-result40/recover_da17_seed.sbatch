#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=128G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-seed
#SBATCH --output=experiments/trace-v21-execution-verified-provenance-result40/receipts/seed-da17-%j.out
#SBATCH --error=experiments/trace-v21-execution-verified-provenance-result40/receipts/seed-da17-%j.err
source experiments/trace-v21-execution-verified-provenance-result40/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/recover_da17_seed.py
