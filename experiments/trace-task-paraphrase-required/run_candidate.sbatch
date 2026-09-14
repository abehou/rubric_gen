#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=32
#SBATCH --mem=512G
#SBATCH --time=24:00:00
#SBATCH --job-name=trace-task-required-candidate
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-task-paraphrase-required/candidate-%j.log
set -euo pipefail
cd /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
export PYTHONPATH="$PWD/src" RUBRIC_GEN_PROJECT_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TRACE_CANDIDATE_ROOT=/home/aydanh/runs/trace-task-paraphrase-required-20260914
export BIOMNIBENCH_LIVE_ROOT="$TRACE_CANDIDATE_ROOT/canonical/live"
export TMPDIR="/scratch/job_tmp/${SLURM_JOB_ID}"
export XDG_CACHE_HOME="$TRACE_CANDIDATE_ROOT/cache"
export UV_CACHE_DIR="$XDG_CACHE_HOME/uv" MPLCONFIGDIR="$XDG_CACHE_HOME/matplotlib"
mkdir -p "$TMPDIR" "$BIOMNIBENCH_LIVE_ROOT" "$XDG_CACHE_HOME" "$UV_CACHE_DIR" "$MPLCONFIGDIR"
exec /data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python experiments/trace-task-paraphrase-required/run_candidate.py
