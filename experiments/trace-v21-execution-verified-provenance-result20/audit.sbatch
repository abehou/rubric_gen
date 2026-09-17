#!/usr/bin/env bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
#SBATCH --mem=256G
#SBATCH --time=48:00:00
#SBATCH --job-name=rtt-r20-audit
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/logs/audit-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/logs/audit-%j.err
source /home/aydanh/repos/rubric_gen/runs/babel-code/trace-v21-result20-20260917/experiments/trace-v21-execution-verified-provenance-result20/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python experiments/trace-v21-execution-verified-provenance-result20/run.py audit
