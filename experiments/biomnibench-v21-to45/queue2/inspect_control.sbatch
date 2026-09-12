#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --job-name=trace-q2-control-read
#SBATCH --output=experiments/biomnibench-v21-to45/queue2/control-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue2/control-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/biomnibench-v21-to45/queue2/inspect_control.py
