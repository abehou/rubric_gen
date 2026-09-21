#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=48:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r50-revise
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result50-extension-20260921/logs/revise-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result50-extension-20260921/logs/revise-%j.err
source experiments/trace-v21-execution-verified-provenance-result50/common.sbatch
export RESULT40_EXPECTED_CPUS=32
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result50/run.py execute
