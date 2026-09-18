#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40-inspect
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/inspect-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/inspect-%j.err
source experiments/trace-v21-execution-verified-provenance-result40/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/reconcile_recovery.py
