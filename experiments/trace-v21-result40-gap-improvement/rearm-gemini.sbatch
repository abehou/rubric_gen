#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --qos=normal
#SBATCH --gres=gpu:A6000:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40-gap-gemini-rearm
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/gemini-rearm-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/gemini-rearm-%j.err
source experiments/trace-v21-result40-gap-improvement/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-result40-gap-improvement/rearm_gemini.py
