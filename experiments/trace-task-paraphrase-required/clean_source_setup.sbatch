#!/bin/bash
# Canonical fresh BioMNIBench-DA source setup on NAS1. No historical inputs.
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-clean-source
#SBATCH --output=/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/experiments/trace-task-paraphrase-required/clean-source-%j.log
set -euo pipefail
umask 077
ROOT=/home/aydanh/runs/rtt-clean-20260915
SOURCE="$ROOT/source"
PY=/home/aydanh/repos/rubric_gen/.venv/bin/python
mkdir -p "$ROOT" "$SOURCE"
export HF_HOME="/scratch/job_tmp/${SLURM_JOB_ID}/hf-home"
export XDG_CACHE_HOME="/scratch/job_tmp/${SLURM_JOB_ID}/xdg-cache"
export TMPDIR="/scratch/job_tmp/${SLURM_JOB_ID}"
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"
if [ -z "${HF_TOKEN:-}" ] && [ -r /home/aydanh/.cache/huggingface/token ]; then
  export HF_TOKEN="$(< /home/aydanh/.cache/huggingface/token)"
fi
[ -n "${HF_TOKEN:-}" ] || { echo 'Hugging Face token unavailable' >&2; exit 2; }
cp /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/download_biomni.py "$SOURCE/download_biomni.py"
cd "$SOURCE"
"$PY" - <<'PY'
import json, os
from pathlib import Path
from datetime import datetime, timezone
from huggingface_hub import HfApi
root=Path.cwd()
token=os.environ['HF_TOKEN']
try:
    info=HfApi(token=token).dataset_info('phylobio/BiomniBench-DA')
    rec={'repo_id':'phylobio/BiomniBench-DA','access':'success','revision':info.sha,'timestamp':datetime.now(timezone.utc).isoformat()}
except Exception as exc:
    rec={'repo_id':'phylobio/BiomniBench-DA','access':'failure','error_type':type(exc).__name__,'error':str(exc)[:300], 'timestamp':datetime.now(timezone.utc).isoformat()}
    (root/'source-access.json').write_text(json.dumps(rec,indent=2)+'\n')
    raise
(root/'source-access.json').write_text(json.dumps(rec,indent=2)+'\n')
print(json.dumps({k:rec[k] for k in ('repo_id','access','revision')}))
PY
# A partial current download is disposable; never mix it with old data.
if [ -d "$SOURCE/data/biomnibench-da" ] && [ ! -f "$SOURCE/source-complete.json" ]; then
  rm -rf -- "$SOURCE/data/biomnibench-da"
fi
"$PY" "$SOURCE/download_biomni.py"
"$PY" - <<'PY'
import hashlib, json
from pathlib import Path
root=Path.cwd(); data=root/'data'/'biomnibench-da'
expected={'da-3-4','da-11-1','da-18-1'}
if not data.is_dir(): raise SystemExit('download did not create data root')
tasks={p.name for p in data.iterdir() if p.is_dir()}
missing=expected-tasks
if missing: raise SystemExit(f'missing canonical tasks: {sorted(missing)}')
checks={}
for task in sorted(expected):
    t=data/task
    required=[t/'instruction.md',t/'tests'/'rubric.txt',t/'environment'/'data']
    absent=[str(p) for p in required if not p.exists()]
    if absent: raise SystemExit(f'{task} missing required source: {absent}')
    checks[task]={'instruction_bytes':(t/'instruction.md').stat().st_size,'rubric_bytes':(t/'tests'/'rubric.txt').stat().st_size,'data_entries':sum(1 for p in (t/'environment'/'data').rglob('*') if p.is_file())}
access=json.loads((root/'source-access.json').read_text())
manifest={'repo_id':'phylobio/BiomniBench-DA','revision':access['revision'],'source_script_sha256':hashlib.sha256((root/'download_biomni.py').read_bytes()).hexdigest(),'data_root':str(data),'tasks':sorted(expected),'checks':checks}
(root/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(root/'source-complete.json').write_text(json.dumps({'status':'complete','manifest':str(root/'source-manifest.json'),'revision':access['revision']},indent=2)+'\n')
print(json.dumps({'status':'complete','revision':access['revision'],'tasks':sorted(expected),'checks':checks}))
PY
