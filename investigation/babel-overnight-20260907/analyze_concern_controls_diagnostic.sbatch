#!/bin/bash
#SBATCH --job-name=rubric-c1-diagnostic
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --no-requeue
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
MAIN_ROOT=/home/aydanh/repos/rubric_gen
CODE_ROOT="$MAIN_ROOT/runs/babel-code/dev3-concern1-policy"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$CODE_ROOT/src"
export UV_LINK_MODE=copy
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-analysis-uv-${UID}"
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-analysis-${SLURM_JOB_ID}"
cd "$CODE_ROOT"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
cd "$MAIN_ROOT"
"$UV_PROJECT_ENVIRONMENT/bin/python" - <<'PY'
from pathlib import Path
import json,os,hashlib
root=Path('/home/aydanh/repos/rubric_gen')
seal=json.loads((root/'investigation/babel-overnight-20260907/concern-controls-diagnostic-seal.json').read_text())
for name,expected in seal.items():
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected, f'analysis source changed: {name}'
for mode,job in [('controls','10356519')]:
 owner=root/f'runs/babel-overnight-20260907/dispatcher-concern1-policy-{mode}-da-11-1'
 receipts=[p for p in owner.glob('*/launch.json') if json.loads(p.read_text())['job_id']==job]
 assert len(receipts)==1
 p=receipts[0];launch=json.loads(p.read_text());result=json.loads((p.parent/'result.json').read_text())
 assert result == {'exits':[0,0], 'source_unchanged':False, 'success':False}
 assert launch['git_commit']=='8705deca7d42828086cd6b1fc654a7eaabdef947'
 anomaly=json.loads((root/'runs/babel-overnight-20260907/shared-launcher-drift-10356519-10356523.json').read_text())
 mismatches=[]
 for name,expected in launch['source_hashes'].items():
  actual=hashlib.sha256(Path(name).read_bytes()).hexdigest()
  if actual!=expected:
   mismatches.append(name)
   assert name==anomaly['changed_file'] and expected==anomaly['expected_sha256'] and actual==anomaly['actual_sha256']
 assert mismatches==[anomaly['changed_file']]
receipt=root/f'runs/babel-overnight-20260907/controls-diagnostic-job-{os.environ["SLURM_JOB_ID"]}'
receipt.mkdir(exist_ok=False)
(receipt/'launch.json').write_text(json.dumps({'job_id':os.environ['SLURM_JOB_ID'],'dependencies':['10356519'],'source_seal':seal,'scope':'DIAGNOSTIC ONLY: completed native controls with preserved launcher seal violation; not clean experiment acceptance; no providers.'},indent=2)+'\n')
PY
EXP_ID=biomnibench-da-factorial-r10-360789db0d3d
OUT=runs/babel-overnight-20260907/diagnostic-concern1-controls-10356519
"$UV_PROJECT_ENVIRONMENT/bin/python" investigation/babel-overnight-20260907/analyze_babel.py \
 --study "runs/babel-dev3-concern1-policy-controls-20260908/da-11-1/study/$EXP_ID" \
 --audit "runs/babel-dev3-concern1-policy-controls-20260908/da-11-1/audit/$EXP_ID" \
 --contrast user-simulator-static user-simulator-red-team-trace \
 --output "$OUT"
"$UV_PROJECT_ENVIRONMENT/bin/python" investigation/babel-overnight-20260907/policy_exposure.py \
 --analysis "$OUT/analysis.json" --output runs/babel-overnight-20260907/diagnostic-exposure-concern1-controls-10356519
"$UV_PROJECT_ENVIRONMENT/bin/python" investigation/babel-overnight-20260907/feedback_exposure.py \
 --analysis "$OUT/analysis.json" --output runs/babel-overnight-20260907/diagnostic-feedback-concern1-controls-10356519
"$UV_PROJECT_ENVIRONMENT/bin/python" - <<'PY'
from pathlib import Path
import os,json
p=Path('runs/babel-overnight-20260907')/f'controls-diagnostic-job-{os.environ["SLURM_JOB_ID"]}'/'result.json'
p.write_text(json.dumps({'analysis_success':True,'scientific_acceptance':False,'classification':'Preserved launcher integrity failure; diagnostic only','analysis':'runs/babel-overnight-20260907/diagnostic-concern1-controls-10356519/analysis.json'})+'\n')
PY
