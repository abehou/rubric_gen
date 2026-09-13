#!/bin/bash
# Provider-free read-only q6 recovery diagnosis.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:20:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=trace-r30-da13-inspect
#SBATCH --output=experiments/biomnibench-v21-to45/queue6/da13-inspect-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue6/da13-inspect-%j.err
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
exec /home/aydanh/repos/rubric_gen/.venv/bin/python experiments/biomnibench-v21-to45/queue6/inspect_da1_3_revision_targets.py
