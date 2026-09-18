#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=48:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-audit
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/audit-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/audit-%j.err
source experiments/trace-v21-execution-verified-provenance-result40/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/run.py audit
