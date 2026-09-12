#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=trace-q2-tests
#SBATCH --output=experiments/biomnibench-v21-to45/queue2/unit-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue2/unit-%j.err
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}"
export PYTHONPATH="$PWD/src:$PWD/tests:$PWD/scripts/babel" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
PYTHON=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
"$PYTHON" -m pytest -q tests/test_trace_appendix_ablations.py tests/test_trace_defense_v21.py tests/test_trace_defense_v2.py tests/test_user_feedback_factors.py tests/test_pretreatment_reuse.py
"$PYTHON" experiments/biomnibench-v21-to45/queue2/check_inputs.py
