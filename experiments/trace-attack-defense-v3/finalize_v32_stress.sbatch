#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --job-name=trace-v32-finalize
#SBATCH --output=experiments/trace-attack-defense-v3/v32-finalize-%j.log
#SBATCH --error=experiments/trace-attack-defense-v3/v32-finalize-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the committed source checkout}"
export PYTHONPATH="$PWD/src" PYTHONUNBUFFERED=1
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python \
  experiments/trace-attack-defense-v3/finalize_v32_stress.py
