#!/bin/bash
#SBATCH --job-name=cue-pair-orientation
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/cue-pair-orientation-%j.out
set -euo pipefail
exec /home/aydanh/repos/rubric_gen/.venv/bin/python /home/aydanh/repos/rubric_gen/investigation/result20-cue-pair-recovery-20260909/pair_orientation.py
