#!/usr/bin/env bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=rtt-r20-cost
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/logs/cost-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/logs/cost-%j.err
source /home/aydanh/repos/rubric_gen/runs/babel-code/trace-v21-result20-20260917/experiments/trace-v21-execution-verified-provenance-result20/common.sbatch
exec /home/aydanh/repos/rubric_gen/.venv/bin/python experiments/trace-v21-execution-verified-provenance-result20/analyze_costs.py
