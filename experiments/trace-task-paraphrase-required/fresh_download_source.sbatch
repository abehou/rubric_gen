#!/bin/bash
# Fresh canonical BioMNIBench-DA source installation using the repository's
# documented download_biomni.py route. This is setup only; no model calls.
#SBATCH --account=dfried
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --job-name=trace-fresh-source
#SBATCH --output=/home/aydanh/runs/trace-task-paraphrase-required-fresh-20260914/source-%j.log
set -euo pipefail

ROOT=/home/aydanh/runs/trace-task-paraphrase-required-fresh-20260914
mkdir -p "$ROOT" "$ROOT/cache"
cp /home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2-exec-571965a/download_biomni.py "$ROOT/download_biomni.py"
export HF_HOME="/scratch/job_tmp/${SLURM_JOB_ID}/hf-home"
export XDG_CACHE_HOME="/scratch/job_tmp/${SLURM_JOB_ID}/xdg-cache"
export TMPDIR="/scratch/job_tmp/${SLURM_JOB_ID}"
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"
cd "$ROOT"
/home/aydanh/repos/rubric_gen/.venv/bin/python download_biomni.py
/home/aydanh/repos/rubric_gen/.venv/bin/python - <<'PY'
from pathlib import Path
import hashlib, json
root=Path('/home/aydanh/runs/trace-task-paraphrase-required-fresh-20260914')
data=root/'data'/'biomnibench-da'
tasks=sorted(p.name for p in data.iterdir() if p.is_dir())
manifest={'source_script_sha256':hashlib.sha256((root/'download_biomni.py').read_bytes()).hexdigest(),'repo_id':'phylobio/BiomniBench-DA','tasks':tasks,'data_root':str(data)}
(root/'source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest))
PY
