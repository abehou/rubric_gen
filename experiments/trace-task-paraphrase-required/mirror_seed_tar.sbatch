#!/bin/bash
# One bounded, provider-free attempt to stage exact frozen da-11-1 seed bytes
# on NAS1.  This is execution recovery only; the source is never rewritten.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-seed-mirror
#SBATCH --output=/home/aydanh/runs/trace-task-paraphrase-required-20260914/seed-mirror-%j.log
set -euo pipefail

SRC=/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21-compatible/inputs/da-11-1/seed
DST=/home/aydanh/runs/trace-task-paraphrase-required-20260914/frozen-input-mirror/seed/da-11-1
mkdir -p "$DST"

for rep in 001 002 003; do
  src_rel="tasks/da-11-1/rep-${rep}"
  tmp="$DST/.rep-${rep}.tmp-$$"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  echo "[$(date -Is)] staging $src_rel" >&2
  if timeout 900s bash -c 'tar -C "$1" -cf - "$2" | tar -C "$3" -xf -' _ "$SRC" "$src_rel" "$tmp"; then
    rm -rf "$DST/rep-${rep}"
    mv "$tmp/$src_rel" "$DST/rep-${rep}"
    rmdir -p "$tmp/tasks/da-11-1" 2>/dev/null || true
    echo "[$(date -Is)] complete rep-${rep}" >&2
  else
    rc=$?
    echo "[$(date -Is)] failed rep-${rep} rc=$rc; discarding partial" >&2
    rm -rf "$tmp"
    exit "$rc"
  fi
done

python3 - "$DST" <<'PY'
import pathlib, sys
root=pathlib.Path(sys.argv[1])
rows=[]
for rep in ('001','002','003'):
    p=root/f'rep-{rep}'
    files=[x for x in p.rglob('*') if x.is_file()]
    rows.append((rep,len(files),sum(x.stat().st_size for x in files)))
print({'destination':str(root),'replicates':rows})
PY
date -Is > "$DST/COMPLETE"
