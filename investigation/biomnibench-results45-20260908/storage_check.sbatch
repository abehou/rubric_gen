#!/bin/bash
#SBATCH --job-name=rubric-storage-check
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:05:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
python3 - <<'PY'
import json,os,pathlib,shutil,socket,subprocess
paths=['/home/aydanh','/data/user_data/aydanh','/data','/scratch','/local','/tmp']
if os.environ.get('SLURM_TMPDIR'):paths.append(os.environ['SLURM_TMPDIR'])
rows=[]
for p in dict.fromkeys(paths):
    exists=os.path.isdir(p);row=dict(path=p,exists=exists)
    if exists:
        u=shutil.disk_usage(p);row.update(total=u.total,free=u.free,writable=os.access(p,os.W_OK))
        row['mount']=subprocess.run(['findmnt','-T',p,'-n','-o','TARGET,SOURCE,FSTYPE'],capture_output=True,text=True).stdout.strip()
    rows.append(row)
result=dict(job=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),paths=rows)
out=pathlib.Path('runs')/('results45-storage-check-'+os.environ['SLURM_JOB_ID']);out.mkdir(exist_ok=False)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
PY
