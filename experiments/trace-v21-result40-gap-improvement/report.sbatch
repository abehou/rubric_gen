#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --qos=normal
#SBATCH --gres=gpu:A6000:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40-gap-report
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/report-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/report-%j.err
source experiments/trace-v21-result40-gap-improvement/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-result40-gap-improvement/analyze.py
