#!/usr/bin/env bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=rtt-r20-prepare
#SBATCH --output=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/logs/prepare-%j.out
#SBATCH --error=/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/logs/prepare-%j.err
source /home/aydanh/repos/rubric_gen/runs/babel-code/trace-v21-result20-20260917/experiments/trace-v21-execution-verified-provenance-result20/common.sbatch
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python

"$PY" -m pytest -q \
  tests/test_trace_task_paraphrase_required.py \
  tests/test_trace_task_required_enforced.py \
  tests/test_execution_verified_dropout.py \
  -k 'not canonical_design_has_six_named_cells and not high_allocation_changes_only_attack_pair_quality_and_diagnosis and not proactive_candidate_changes_only_diagnosis_reasoning_and_solver_guidance and not proactive_local_runner_is_wired_to_the_saved_case_gate and not provenance_local_runner_preserves_high_proposer_only_allocation'

"$PY" -m pytest -q \
  tests/test_runtime_capacity.py \
  tests/test_biomnibench_scale_dispatch.py \
  tests/test_runtime_throughput.py::test_audit_owned_stages_share_pool_and_leave_capacity_for_other_provider \
  tests/test_runtime_throughput.py::test_audit_provider_partitions_schedule_sixty_each_without_cross_consumption

/home/aydanh/tools/uv/uv run --no-sync rubric-gen --help >/dev/null
exec "$PY" experiments/trace-v21-execution-verified-provenance-result20/prepare.py
