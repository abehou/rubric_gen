#!/bin/bash
#SBATCH --job-name=cue-sol-artifacts
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:45:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/cue-sol-supervision-%j.out
set -euo pipefail
export PYTHONPATH=/home/aydanh/repos/rubric_gen/runs/babel-code/result20-cue-original-audit/src
exec /home/aydanh/repos/rubric_gen/.venv/bin/python /home/aydanh/repos/rubric_gen/investigation/cue-sol-supervision-20260909/verify_artifacts.py
