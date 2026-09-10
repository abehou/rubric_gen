#!/bin/bash
#SBATCH --job-name=rubric-plot-smoke
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:15:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
MAIN_ROOT=$PWD
cd runs/babel-code/result20-current
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="${SLURM_TMPDIR:-/tmp}/rubric-report-smoke-${UID}-${SLURM_JOB_ID}"
export UV_CACHE_DIR="${SLURM_TMPDIR:-/tmp}/rubric-gen-uv-${UID}"
export MPLCONFIGDIR="${SLURM_TMPDIR:-/tmp}/rubric-mpl-${UID}-${SLURM_JOB_ID}"
uv venv --python /usr/bin/python3.12 "$UV_PROJECT_ENVIRONMENT"
uv sync --frozen --python /usr/bin/python3.12
cd "$MAIN_ROOT"
"$UV_PROJECT_ENVIRONMENT/bin/python" - <<'PY'
import hashlib,importlib.util,json,os,socket,tempfile,time
from pathlib import Path
start=time.time();p=Path('investigation/result20-report-20260908/plot_results.py')
sha=hashlib.sha256(p.read_bytes()).hexdigest()
spec=importlib.util.spec_from_file_location('plots',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows=[]
for c in m.CONDITIONS:
 for task in range(20):
  for rep in (1,2,3):
   for model in sorted(m.PANEL):
    rows.append(dict(condition_id=c,task_id=str(task),replicate=rep,model=model,values=dict(W=60,W_train=50,S=55,H=52,A=40,WS=5,SH=3,HA=12,WA=20),strong_master=58,direct={w:dict(decision='abstain' if model=='claude-opus-5' else 'no_reward_hacking_detected',score=2) for w in m.WINDOWS}))
data=m.tables({'rows':rows})
with tempfile.TemporaryDirectory(prefix='synthetic-render-only-') as tmp:
 root=Path(tmp);m.plot(data,root)
 files={f.name:f.stat().st_size for f in root.glob('*.png')}
 assert len(files)==2 and all(n>10000 for n in files.values()),files
assert hashlib.sha256(p.read_bytes()).hexdigest()==sha
out=Path('runs/babel-result20-current-20260908')/f'report-render-smoke-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
result=dict(success=True,scope='Non-scientific synthetic rendering smoke; temporary figures removed; no experiment or provider calls',job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),plot_source_sha256=sha,files_rendered=files,elapsed_seconds=time.time()-start)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
PY
