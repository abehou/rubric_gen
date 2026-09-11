#!/bin/bash
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:15:00
#SBATCH --job-name=trace-v3-inventory
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/experiments/trace-attack-defense-v3/inventory-%j.log
set -euo pipefail
ROOT=/data/user_data/aydanh/rubric_gen/runs
printf '{"job":"%s","host":"%s","roots":[' "$SLURM_JOB_ID" "$(hostname)"
first=1
find "$ROOT" -maxdepth 3 -type d \( -iname '*v21*' -o -iname '*v2.1*' -o -iname '*dev3*' \) -print0 | while IFS= read -r -d '' path; do
  if [ "$first" -eq 0 ]; then printf ','; fi
  first=0
  python3 -c 'import json,sys; print(json.dumps(sys.argv[1]),end="")' "$path"
done
printf ']}\n'
