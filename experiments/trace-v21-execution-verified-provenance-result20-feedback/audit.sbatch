#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --gres=gpu:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=48:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r20fb-audit
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920/logs/audit-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920/logs/audit-%j.err
source experiments/trace-v21-execution-verified-provenance-result20-feedback/common.sbatch
export RESULT20_FEEDBACK_EXPECTED_CPUS=8
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result20-feedback/run.py audit
