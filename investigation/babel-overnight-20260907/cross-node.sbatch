#!/bin/bash
#SBATCH --job-name=rubric-cross-node
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=2
#SBATCH --ntasks=2
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
export PYTHONPATH="$PWD/src"
export PYTHONDONTWRITEBYTECODE=1
# No .env.local load, model command or scientific data access.
srun /usr/bin/python3.12 investigation/babel-overnight-20260907/cross_node_capacity.py
