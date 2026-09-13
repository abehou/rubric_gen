#!/bin/bash
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --account=dfried
#SBATCH --job-name=trace-cleanup-cache-six
#SBATCH --output=experiments/biomnibench-v21-to45/queue8/cleanup-cache-six-%j.log
#SBATCH --error=experiments/biomnibench-v21-to45/queue8/cleanup-cache-six-%j.err
set -euo pipefail
root=/data/user_data/aydanh/rubric_gen/cache/environments
target="$root/a5f86d3f89f6256c-be8151e15cce-10380168"
active="$root/trace-repair-10381602"
if [ "$target" = "$active" ]; then echo "refusing active path"; exit 2; fi
if [ ! -e "$target" ]; then echo "absent $target"; exit 0; fi
if [ ! -d "$target" ] || [ -L "$target" ]; then echo "refusing non-directory $target"; exit 2; fi
find "$target" -depth -type f -delete
find "$target" -depth -type l -delete
find "$target" -depth -type d -empty -delete
rmdir "$target"
echo "removed $target"
df -h /data/user_data/aydanh || true
df -i /data/user_data/aydanh || true
