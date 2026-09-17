#!/usr/bin/env bash
#SBATCH --job-name=rtt-r20-stage
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=/home/aydanh/runs/rtt-result20-staging-%j.out
#SBATCH --error=/home/aydanh/runs/rtt-result20-staging-%j.err

set -euo pipefail

BASE=/data/user_data/aydanh/rubric_gen
RUN="$BASE/runs/rtt-result20-next"
LIVE="$BASE/live/rtt-result20-next"
CACHE="$BASE/cache/rtt-result20-next"
POOL="$BASE/pools/biomnibench/rtt-result20-next"
RECEIPT="$RUN/owners/setup-${SLURM_JOB_ID}.txt"

mkdir -p \
  "$RUN/owners" "$RUN/logs" "$RUN/inputs" "$RUN/study" "$RUN/audit" "$RUN/reports" \
  "$LIVE" "$CACHE" "$POOL/seeds" "$POOL/paraphrases" "$POOL/pretreatment"

exec > >(tee "$RECEIPT") 2>&1
printf 'timestamp\t%s\n' "$(date --iso-8601=seconds)"
printf 'hostname\t%s\n' "$(hostname)"
printf 'slurm_job_id\t%s\n' "$SLURM_JOB_ID"

for path in "$RUN" "$LIVE" "$CACHE" "$POOL"; do
  test -d "$path"
  test ! -L "$path"
  test "$(stat -c %u "$path")" = "$(id -u)"
  probe="$path/.write-probe-${SLURM_JOB_ID}"
  printf 'nas8-write-check\n' > "$probe"
  sync "$probe"
  rm -f "$probe"
  printf 'writable\t%s\n' "$path"
done

printf 'aggregate_provider_concurrency\t60\n'
printf 'audit_studies\t1\n'
printf 'provider_calls\t0\n'
printf 'scientific_inputs\tnot_staged\n'
printf 'result20_authorized\tfalse\n'

findmnt --noheadings --output SOURCE,FSTYPE,OPTIONS --target "$RUN"
df -B1 "$RUN"
df -i "$RUN"
