#!/bin/bash
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src:$PWD/tests:$PWD/scripts/babel" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
export TMPDIR=/data/user_data/aydanh/rubric_gen/cache/runtime-throughput/tmp-q3-checks
mkdir -p "$TMPDIR"
PYTHON=/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python
"$PYTHON" experiments/biomnibench-v21-to45/queue3/make_configs.py
"$PYTHON" -m pytest -q tests/test_trace_feedback_matrix.py tests/test_trace_appendix_ablations.py tests/test_trace_defense_v21.py tests/test_trace_defense_v2.py tests/test_user_feedback_factors.py tests/test_pretreatment_reuse.py
"$PYTHON" experiments/biomnibench-v21-to45/queue3/check_inputs.py
