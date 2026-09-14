#!/bin/bash
# Narrow provider-free check: bounded stat/test calls only; no recursive scan.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --job-name=trace-task-required-path2
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-task-paraphrase-required/path2-%j.log
set -euo pipefail
ROOT=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2
RUN=/home/aydanh/runs/trace-task-paraphrase-required-20260914
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1

probe_dir() {
  local label="$1" path="$2"
  echo "CHECK $label $path"
  timeout 15s stat -c '%F %u:%g %a %n' "$path"
  test -d "$path"
}

mkdir -p "$RUN/canonical"
probe_dir "candidate_root" "$RUN"
for task in da-3-4 da-11-1 da-18-1; do
  probe_dir "seed_$task" "/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21-compatible/inputs/$task/seed"
  probe_dir "paraphrase_$task" "/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/inputs/$task/paraphrase"
  probe_dir "tasks_$task" "/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/inputs/tasks/$task"
done

# Check the exact new writable parent without creating scientific state.
probe_dir "new_canonical_parent" "$RUN/canonical"
probe="$RUN/canonical/.path-write-probe"
printf '%s\n' home-path-ok > "$probe"
test "$(cat "$probe")" = home-path-ok
rm -f -- "$probe"

cat > "$RUN/path-validation.json" <<EOF
{
  "stage": "provider_free_home_path_validation_narrow",
  "job": "${SLURM_JOB_ID}",
  "host": "$(hostname)",
  "candidate_root": "$RUN",
  "frozen_inputs_stat_checked": true,
  "new_home_write_checked": true,
  "scientific_calls": 0,
  "note": "bounded stat/test only; no recursive scan or provider call"
}
EOF
cat "$RUN/path-validation.json"
