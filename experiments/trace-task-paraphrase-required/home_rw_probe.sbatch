#!/bin/bash
# Provider-free compute-node check of the NAS1 execution path.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:10:00
#SBATCH --job-name=trace-home-rw
#SBATCH --output=/home/aydanh/runs/trace-task-paraphrase-required-20260914/home-rw-%j.log
set -u
target=/home/aydanh/runs/trace-task-paraphrase-required-20260914
echo "node=$(hostname)"
findmnt -T "$target" -o TARGET,SOURCE,FSTYPE,OPTIONS 2>/dev/null || true
df -hT "$target" || true
probe="$target/.compute-rw-probe-$$"
if printf 'ok\n' > "$probe" 2>/tmp/trace-home-rw.err; then
  echo "write_ok=$probe"
  if rm -f "$probe"; then echo "remove_ok"; else echo "remove_failed"; fi
else
  echo "write_failed"
  cat /tmp/trace-home-rw.err 2>/dev/null || true
fi
echo "partial_tmp_exists=$(test -e "$target/frozen-input-mirror/seed/da-11-1/.rep-001.tmp-2121363" && echo yes || echo no)"
if rmdir "$target/frozen-input-mirror/seed/da-11-1/.rep-001.tmp-2121363" 2>/tmp/trace-home-rmdir.err; then
  echo "partial_tmp_remove_ok"
else
  echo "partial_tmp_remove_failed"
  cat /tmp/trace-home-rmdir.err 2>/dev/null || true
fi
