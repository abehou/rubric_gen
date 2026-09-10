#!/bin/bash
#SBATCH --job-name=cue-application-check
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:45:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/cue-application-check-%j.out
set -euo pipefail
export PYTHONPATH=/home/aydanh/repos/rubric_gen/runs/babel-code/result20-cue-original-audit/src
exec /home/aydanh/repos/rubric_gen/.venv/bin/python /home/aydanh/repos/rubric_gen/investigation/cue-application-check-20260909/diagnostic.py run
