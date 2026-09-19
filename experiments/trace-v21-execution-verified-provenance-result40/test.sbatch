#!/usr/bin/env bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=rtt-r40-tests
#SBATCH --output=experiments/trace-v21-execution-verified-provenance-result40/receipts/tests-%j.out
#SBATCH --error=experiments/trace-v21-execution-verified-provenance-result40/receipts/tests-%j.err
set -euo pipefail
ROOT="${SLURM_SUBMIT_DIR:?Slurm submit directory is required}"
export RESULT40_CONFIG_BUNDLE=/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918/experiments/trace-v21-execution-verified-provenance-result40
export RUBRIC_GEN_PATH_MAP_FILE="$ROOT/experiments/trace-v21-execution-verified-provenance-result40/path-map.json"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd "$ROOT"
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
"$PY" -m pytest -q experiments/trace-v21-execution-verified-provenance-result40/test_runtime.py
"$PY" -m pytest -q tests/test_execution_verified_dropout.py \
  -k 'not canonical_design and not high_allocation_changes and not proactive_candidate_changes and not proactive_local_runner and not provenance_local_runner'
"$PY" -m pytest -q tests/test_runtime_throughput.py::test_audit_provider_partitions_schedule_sixty_each_without_cross_consumption
"$PY" -m pytest -q tests/test_trace_result20_audit_bootstrap.py
