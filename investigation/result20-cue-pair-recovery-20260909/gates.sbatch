#!/bin/bash
#SBATCH --job-name=cue-active-gates
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/cue-active-gates-%j.out
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
exec .venv/bin/python investigation/result20-cue-pair-recovery-20260909/evaluate.py /data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/comparison-recovered-v3/analysis.json /data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/comparison-recovered-v3/joint-gates.json
