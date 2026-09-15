#!/bin/bash
# Read-only inventory of exact historical RTT/BioMNIBench roots before retirement.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:20:00
#SBATCH --job-name=trace-retire-inv
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/retire-inventory-%j.log
set -u
OUT=/home/aydanh/runs/rtt-clean-20260915
mkdir -p "$OUT"
{
  date -Is
  hostname
  echo '--- NAS8 filesystem ---'
  df -hT /data/user_data/aydanh 2>&1 || true
  df -i /data/user_data/aydanh 2>&1 || true
  echo '--- NAS1 filesystem ---'
  df -hT /home/aydanh
  df -i /home/aydanh
  echo '--- explicit historical roots ---'
  for p in \
    /data/user_data/aydanh/rubric_gen/runs/trace-task-paraphrase-required-20260913 \
    /data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911 \
    /data/user_data/aydanh/rubric_gen/runs/trace-task-paraphrase-required-20260914 \
    /data/user_data/aydanh/rubric_gen/runs/trace-task-paraphrase-required-fresh-20260914 \
    /home/aydanh/runs/trace-task-paraphrase-required-20260914 \
    /home/aydanh/runs/trace-task-paraphrase-required-fresh-20260914; do
    if [ -e "$p" ] || [ -L "$p" ]; then
      printf 'EXISTS\t'; stat -c '%U\t%F\t%n' "$p" 2>&1 || true
      du -x -sh "$p" 2>&1 || true
      du -x --inodes -s "$p" 2>&1 || true
    else
      printf 'ABSENT\t%s\n' "$p"
    fi
  done
  echo '--- plausible run roots (bounded immediate listing) ---'
  for base in /data/user_data/aydanh/rubric_gen/runs /home/aydanh/runs; do
    echo "BASE $base"
    if [ -d "$base" ]; then
      find "$base" -mindepth 1 -maxdepth 1 -type d \( -iname '*trace*' -o -iname '*biomnibench*' \) -printf '%p\n' 2>/dev/null | sort
    fi
  done
} > "$OUT/retire-inventory-$SLURM_JOB_ID.txt"
cat "$OUT/retire-inventory-$SLURM_JOB_ID.txt"
