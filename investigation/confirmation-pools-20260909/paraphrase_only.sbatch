#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --job-name=confirm-paraphrases
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/confirm-paraphrases-%j.out
set -euo pipefail
umask 077
export PYTHONPATH=/home/aydanh/repos/rubric_gen/runs/babel-code/result20-cue-ranking/src
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/confirmation
export TMPDIR=/data/user_data/aydanh/rubric_gen/tmp/confirmation
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR"
exec /home/aydanh/repos/rubric_gen/.venv/bin/python /home/aydanh/repos/rubric_gen/investigation/confirmation-pools-20260909/paraphrase_only.py
