#!/bin/bash
# Exact user-authorized retirement of obsolete RTT run roots on NAS1.
# No source code, reports, or current execution checkout are touched.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=01:00:00
#SBATCH --job-name=trace-retire-home
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/retire-home-%j.log
set -euo pipefail
OUT=/home/aydanh/runs/rtt-clean-20260915
mkdir -p "$OUT"
exec > >(tee "$OUT/retire-home-$SLURM_JOB_ID.txt") 2>&1
date -Is
hostname
df -hT /home/aydanh
df -i /home/aydanh
for p in \
  /home/aydanh/runs/trace-task-paraphrase-required-20260914 \
  /home/aydanh/runs/trace-task-paraphrase-required-fresh-20260914; do
  if [ -e "$p" ] || [ -L "$p" ]; then
    owner=$(stat -c '%U' "$p")
    [ "$owner" = aydanh ] || { echo "unexpected owner: $p=$owner"; exit 4; }
    [ ! -L "$p" ] || { echo "refusing symlink: $p"; exit 4; }
    printf 'RETIRING %s\n' "$p"
    du -sh "$p"
    du --inodes -s "$p"
    rm -rf -- "$p"
  else
    printf 'ABSENT %s\n' "$p"
  fi
done
date -Is
df -hT /home/aydanh
df -i /home/aydanh
