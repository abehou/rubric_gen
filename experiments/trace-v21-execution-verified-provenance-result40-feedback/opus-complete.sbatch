#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=r40fb-opus
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-feedback-policies-20260920/logs/opus-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-feedback-policies-20260920/logs/opus-%j.err
source experiments/trace-v21-execution-verified-provenance-result40-feedback/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40-feedback/run.py audit-opus-complete
