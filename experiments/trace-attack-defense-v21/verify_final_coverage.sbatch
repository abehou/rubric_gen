#!/bin/bash
# Provider-free verification; never launches a judgment.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-v21-coverage
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v21/coverage-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src"
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/live
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/tmp
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v21/result20
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v21/verify_final_coverage.py
