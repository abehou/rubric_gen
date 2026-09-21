#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=32:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40-gap-revise
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/revise-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/revise-%j.err
source experiments/trace-v21-result40-gap-improvement/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-result40-gap-improvement/run.py execute --scope remaining
