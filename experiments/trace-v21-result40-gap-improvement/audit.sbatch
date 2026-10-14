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
#SBATCH --job-name=r40-gap-audit
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/audit-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result40-gap-improvement-pilot-20260921/logs/audit-%j.err
if [[ $# -ne 2 || "$2" != "opus" ]]; then
  echo "usage: sbatch audit.sbatch TASK opus" >&2
  echo "Sol must use recover-sol.sbatch to preserve historical successes" >&2
  exit 2
fi
source experiments/trace-v21-result40-gap-improvement/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python \
  experiments/trace-v21-result40-gap-improvement/audit_sol_opus.py \
  --task "$1" --provider "$2" --max-concurrency 60
