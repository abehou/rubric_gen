#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:a6000:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:45:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40-dev-forensics
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921/logs/forensics-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921/logs/forensics-%j.err
source experiments/trace-v21-result40-development-gap/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-result40-development-gap/export_trajectories.py
