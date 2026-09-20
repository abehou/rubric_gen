#!/usr/bin/env bash
#SBATCH --partition=general
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --gres=gpu:1
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-gemini-one
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/gemini-one-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918/logs/gemini-one-%j.err
source experiments/trace-v21-execution-verified-provenance-result40/common.sbatch
export RESULT40_SOURCE_COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-execution-verified-provenance-result40/recover_old20_current_gemini.py
