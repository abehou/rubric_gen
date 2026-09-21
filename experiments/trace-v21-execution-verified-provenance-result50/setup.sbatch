#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r50-setup
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result50-extension-20260921/logs/setup-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result50-extension-20260921/logs/setup-%j.err
source experiments/trace-v21-execution-verified-provenance-result50/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result50/prepare.py
