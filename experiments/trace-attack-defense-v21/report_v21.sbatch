#!/bin/bash
# Provider-free final analysis/reporting over sealed v2.1 outputs.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --job-name=trace-v21-report
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v21/report-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src:$PWD/scripts/diagnostics:$PWD/experiments/trace-attack-defense-v21/report"
export RUBRIC_GEN_PROJECT_ROOT="$PWD"
export PYTHONDONTWRITEBYTECODE=1
export BIOMNIBENCH_LIVE_ROOT=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/live
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/tmp
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v21/result20
export UV_CACHE_DIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v21/result20/uv
export MPLCONFIGDIR=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v21/result20/matplotlib
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR"
PY=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
for module in report_sources report_outcomes report_pipeline report_timing report_costs report_accounting report_gaps report_positives; do
  echo "REPORT_STAGE $module" >&2
  "$PY" "experiments/trace-attack-defense-v21/report/${module}.py"
done
"$PY" experiments/trace-attack-defense-v21/report/report_case_review_auto.py
"$PY" experiments/trace-attack-defense-v21/report/report_gap_review_auto.py
"$PY" experiments/trace-attack-defense-v21/report/report_figures.py
"$PY" experiments/trace-attack-defense-v21/report/render_report.py
