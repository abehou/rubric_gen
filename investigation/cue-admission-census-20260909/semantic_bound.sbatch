#!/bin/bash
#SBATCH --job-name=cue-admission-census
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:45:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/cue-semantic-bound-%j.out
set -euo pipefail
export PYTHONPATH=/home/aydanh/repos/rubric_gen/runs/babel-code/result20-cue-contrast/src
exec /home/aydanh/repos/rubric_gen/.venv/bin/python /home/aydanh/repos/rubric_gen/investigation/cue-admission-census-20260909/semantic_bound.py
