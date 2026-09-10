#!/bin/bash
#SBATCH --job-name=cue-filter-data
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/cue-filter-data-%j.out
set -euo pipefail
exec /home/aydanh/repos/rubric_gen/.venv/bin/python /home/aydanh/repos/rubric_gen/investigation/cue-application-reasoning-20260909/verify_filter_data.py
