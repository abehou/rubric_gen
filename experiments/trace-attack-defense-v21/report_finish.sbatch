#!/bin/bash
# Provider-free completion of rendering over already-written report tables.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-v21-report-finish
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v21/report-finish-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src:$PWD/scripts/diagnostics:$PWD/experiments/trace-attack-defense-v21/report"
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/live
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/tmp
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v21/result20
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v21/result20/matplotlib
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$MPLCONFIGDIR"
PY=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
"$PY" experiments/trace-attack-defense-v21/report/report_case_review_auto.py
"$PY" experiments/trace-attack-defense-v21/report/report_gap_review_auto.py
"$PY" experiments/trace-attack-defense-v21/report/report_figures.py
"$PY" experiments/trace-attack-defense-v21/report/render_report.py
