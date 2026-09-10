#!/bin/bash
#SBATCH --job-name=rubric-r20-user-static-report
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=02:00:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
MAIN_ROOT=$PWD
CODE_ROOT="$MAIN_ROOT/runs/babel-code/result20-checkpoint-recovery"
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$CODE_ROOT/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-static-report-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
cd "$CODE_ROOT"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
cd "$MAIN_ROOT"
"$UV_PROJECT_ENVIRONMENT/bin/python" - <<'PY'
import hashlib,json,os,socket,subprocess,sys,time
from pathlib import Path
root=Path.cwd();code=root/'runs/babel-code/result20-checkpoint-recovery';start=time.time()
seal=json.loads((root/'investigation/result20-report-20260908/user-static-current-analysis-seal.json').read_text())
for name,expected in seal.items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
owner=root/'runs/babel-overnight-20260907/dispatcher-user-static-result20-checkpoint-recovery'
receipts=[p for p in owner.glob('*/launch.json') if json.loads(p.read_text())['job_id']=='10357851'];assert len(receipts)==1
producer=receipts[0];launch=json.loads(producer.read_text());result=json.loads((producer.parent/'result.json').read_text())
assert result=={'exits':[0,0],'source_unchanged':True,'success':True},result
assert launch['git_commit']=='1f995dfa53cd51582ce2b3f84db78ceca055a4ea'
for name,expected in launch['source_hashes'].items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==expected,name
receipt=root/f'runs/babel-result20-current-20260908/user-static-report-job-{os.environ["SLURM_JOB_ID"]}';receipt.mkdir(exist_ok=False)
base=root/'runs/babel-result20-current-20260908/user-static';identity=launch['experiment_id'];output=root/'runs/babel-result20-current-20260908/user-static-report-v1'
cmd=[sys.executable,str(code/'investigation/babel-overnight-20260907/analyze_babel.py'),'--study',str(base/'study'/identity),'--audit',str(base/'audit'/identity),'--output',str(output)]
(receipt/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),producer_job='10357851',source_seal=seal,command=cmd,scope='Read-only user-static native coverage and W/S/H/A/direct RH; no providers',output=str(output)),indent=2)+'\n')
with (receipt/'analysis.log').open('w') as log:r=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
unchanged=all(hashlib.sha256((root/n).read_bytes()).hexdigest()==sha for n,sha in seal.items())
(receipt/'result.json').write_text(json.dumps(dict(success=r.returncode==0 and unchanged,exit_code=r.returncode,source_unchanged=unchanged,elapsed_seconds=time.time()-start))+'\n')
raise SystemExit(0 if r.returncode==0 and unchanged else 1)
PY
