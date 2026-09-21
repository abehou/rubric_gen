#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40-dev-preflight
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921/logs/preflight-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921/logs/preflight-%j.err
source experiments/trace-v21-result40-development-gap/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-result40-development-gap/run.py --preflight-only
