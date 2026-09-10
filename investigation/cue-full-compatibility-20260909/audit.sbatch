#!/bin/bash
#SBATCH --job-name=cue-provenance
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/slurm-%x-%j.out
set -euo pipefail
umask 077
python3 investigation/cue-full-compatibility-20260909/audit.py
