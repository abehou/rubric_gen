#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
# The v2.1 canonical control reached the 256G cgroup ceiling during otherwise
# healthy provider work; keep the same 32 CPUs and serialized runner on 512G.
# This changes resource headroom only, not scientific inputs or assignment scope.
#SBATCH --mem=512G
#SBATCH --time=2-00:00:00
#SBATCH --job-name=trace-v31-canonical
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/canonical-v31-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
cd "$ROOT"
export PYTHONPATH="$ROOT/src"
export PYTHONUNBUFFERED=1
export XDG_CACHE_HOME=/data/user_data/aydanh/rubric_gen/cache/trace-attack-defense-v3/canonical-v31
export TMPDIR=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/canonical-v31-tmp
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-attack-defense-v3/canonical_v31_run.py
