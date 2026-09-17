#!/usr/bin/env bash
#SBATCH --job-name=rtt-r20-runtime
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=/home/aydanh/runs/rtt-result20-runtime-%j.out
#SBATCH --error=/home/aydanh/runs/rtt-result20-runtime-%j.err

set -euo pipefail

ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/rtt-result20-staging-20260916
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TMPDIR="/scratch/job_tmp/${SLURM_JOB_ID}"
mkdir -p "$TMPDIR"

"$PY" -m pytest -q \
  tests/test_runtime_capacity.py \
  tests/test_biomnibench_scale_dispatch.py \
  tests/test_runtime_throughput.py::test_audit_owned_stages_share_pool_and_leave_capacity_for_other_provider

"$PY" - <<'PY'
from pathlib import Path
from rubric_gen.runtime.capacity import policy

settings = policy()
assert settings["aggregate_concurrency"] == 60
assert settings["audit_studies"] == 1
root = Path(settings["coordination_dir"])
assert (root / "provider" / "capacity.json").read_text() == '{"version": 1, "capacity": 60}'
assert (root / "audit" / "capacity.json").read_text() == '{"version": 1, "capacity": 1}'
print({"runtime_policy": settings, "provider_calls": 0})
PY
