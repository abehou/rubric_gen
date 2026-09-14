#!/bin/bash
# Sol+Opus audit of the completed 16-assignment provisional cohort.
# Input mirrors are mounted at the recorded NAS8 paths inside an isolated user
# namespace; no writes are made to NAS8.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=8
#SBATCH --mem=256G
#SBATCH --time=2-00:00:00
#SBATCH --job-name=trace-required-audit
#SBATCH --output=/home/aydanh/runs/trace-task-paraphrase-required-20260914/provisional-audit/audit-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a
MIRROR=/home/aydanh/runs/trace-task-paraphrase-required-20260914/provisional-audit/input-mirror
cd "$ROOT"
export PYTHONPATH="$ROOT/src" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
export XDG_CACHE_HOME=/home/aydanh/runs/trace-task-paraphrase-required-20260914/cache/provisional-audit-${SLURM_JOB_ID}
export TMPDIR=/scratch/job_tmp/${SLURM_JOB_ID}
mkdir -p "$XDG_CACHE_HOME" "$TMPDIR"

# Keep the historical input strings in the scientific requests, while mapping
# only those reads to validated NAS1 copies.  A private namespace avoids any
# mutation of the real /data/user_data mount.
export TRACE_MIRROR="$MIRROR"
exec unshare -Urnm /bin/bash -c '
  set -euo pipefail
  mount --make-rprivate /
  mount -t tmpfs -o size=64M trace-audit-inputs /data/user_data
  old=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/inputs
  mkdir -p "$old/tasks" "$old/da-3-4" "$old/da-11-1" "$old/da-18-1"
  mount --bind "$TRACE_MIRROR/inputs/tasks" "$old/tasks"
  for task in da-3-4 da-11-1 da-18-1; do
    mkdir -p "$old/$task/paraphrase"
    mount --bind "$TRACE_MIRROR/inputs/$task/paraphrase" "$old/$task/paraphrase"
  done
  exec /home/aydanh/repos/rubric_gen/.venv/bin/python experiments/trace-task-paraphrase-required/provisional_audit.py "$@"
'
_ "$@"
