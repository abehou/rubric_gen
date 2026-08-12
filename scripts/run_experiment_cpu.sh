#!/usr/bin/env bash
set -euo pipefail

# Run this script from a login node, not from inside an existing reqcpu shell.
# Each attempt receives a fresh four-hour allocation.  The experiment is stopped
# ten minutes early so it has time to record an interrupt-safe resume boundary.

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
experiment_path="${1:-experiment.yaml}"
slice_seconds="${BIOMNIBENCH_SLICE_SECONDS:-13800}"
max_attempts="${BIOMNIBENCH_MAX_ATTEMPTS:-100}"
minimum_retry_seconds="${BIOMNIBENCH_MINIMUM_RETRY_SECONDS:-300}"

if (($# > 1)); then
  echo "usage: $0 [EXPERIMENT_YAML]" >&2
  exit 2
fi
if [[ -n "${SLURM_JOB_ID:-}" ]]; then
  echo "error: run this wrapper on a login node, outside the current reqcpu allocation" >&2
  exit 2
fi
if [[ ! "$slice_seconds" =~ ^[1-9][0-9]*$ ]] \
  || [[ ! "$max_attempts" =~ ^[1-9][0-9]*$ ]] \
  || [[ ! "$minimum_retry_seconds" =~ ^[0-9]+$ ]]; then
  echo "error: BIOMNIBENCH_* timing values must be non-negative integers" >&2
  exit 2
fi

command=(
  uv run biomnibench-agent run
  --experiment "$experiment_path"
  --max-concurrency 64
  --resume
)

started_at="$(date +%s)"
for ((attempt = 1; attempt <= max_attempts; attempt++)); do
  attempt_started_at="$(date +%s)"
  total_elapsed=$((attempt_started_at - started_at))
  printf 'Attempt %d/%d: requesting CPU allocation (elapsed %02d:%02d:%02d)\n' \
    "$attempt" "$max_attempts" \
    "$((total_elapsed / 3600))" "$(((total_elapsed % 3600) / 60))" \
    "$((total_elapsed % 60))"

  set +e
  srun \
    --account=marlowe-m000058 \
    --partition=preempt \
    --nodes=1 \
    --ntasks=1 \
    --cpus-per-task=16 \
    --mem=64G \
    --time=04:00:00 \
    --job-name=biomnibench-agent \
    --chdir="$project_root" \
    timeout --foreground --signal=INT --kill-after=120 \
      "$slice_seconds" "${command[@]}"
  status=$?
  set -e

  attempt_finished_at="$(date +%s)"
  attempt_elapsed=$((attempt_finished_at - attempt_started_at))
  total_elapsed=$((attempt_finished_at - started_at))

  if ((status == 0)); then
    printf 'Experiment completed after %d attempt(s), total runtime %02d:%02d:%02d.\n' \
      "$attempt" "$((total_elapsed / 3600))" \
      "$(((total_elapsed % 3600) / 60))" "$((total_elapsed % 60))"
    exit 0
  fi

  # timeout normally returns 124 (or 137 if its kill grace expires).  Slurm can
  # instead report its own nonzero status when an allocation is preempted.
  if ((status != 124 && status != 137 && attempt_elapsed < minimum_retry_seconds)); then
    echo "error: experiment failed with status $status after ${attempt_elapsed}s; not treating this as an allocation timeout" >&2
    exit "$status"
  fi

  printf 'Allocation attempt ended with status %d after %02d:%02d:%02d; resuming in a fresh allocation.\n' \
    "$status" "$((attempt_elapsed / 3600))" \
    "$(((attempt_elapsed % 3600) / 60))" "$((attempt_elapsed % 60))"
done

echo "error: experiment did not complete after $max_attempts allocation attempts" >&2
exit 1
