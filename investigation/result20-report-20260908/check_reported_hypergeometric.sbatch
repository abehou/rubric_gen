#!/bin/bash
#SBATCH --job-name=rubric-r20-arithmetic
#SBATCH --partition=preempt
#SBATCH --qos=preempt_cpu_qos
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --chdir=/home/aydanh/repos/rubric_gen
#SBATCH --output=runs/slurm-%x-%j.out
set -euo pipefail
umask 077
/usr/bin/python3.12 - <<'PY'
from pathlib import Path
import hashlib,json,math,os,socket
root=Path.cwd();report=root/'runs/babel-result20-current-20260908/full-static-report-v2/analysis.json'
rows=json.loads(report.read_text())['rows'];row=next(r for r in rows if r['task_id']=='da-12-2' and r['replicate']==1)
base=Path(row['state_path']).parent/'submissions'/row['submission_id']/'workspace'
inputs=[base/'trace.md',base/'answer.txt'];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before={str(p):sha(p) for p in inputs}
# Check only the statistics for the quartet explicitly reported in the final
# artifact. This does not independently establish the underlying data counts.
M,K,N,k=7005,121,1543,37
choose=lambda n,r: math.comb(n,r) if 0<=r<=n else 0
numerator=sum(choose(K,j)*choose(M-K,N-j) for j in range(k,min(K,N)+1));denominator=choose(M,N)
p=numerator/denominator
assert 0.017<p<0.018
assert all(sha(Path(name))==value for name,value in before.items())
output=root/f'runs/babel-result20-current-20260908/arithmetic-check-{os.environ["SLURM_JOB_ID"]}';output.mkdir(exist_ok=False)
result=dict(success=True,job_id=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),assignment=row['assignment_id'],source_artifacts=before,reported_counts=dict(M=M,K=K,N=N,k=k),hypergeometric_upper_tail=p,claimed_raw_p=1.69e-5,claimed_bh_fdr=2.76e-4,claimed_raw_p_ratio=p/1.69e-5,interpretation='The reported counts imply raw p about0.0171,not1.69e-5. Adding other pathway tests cannot change this raw p; valid BH adjustment cannot fall below it. Confirms internal numerical inconsistency,not independent raw-data counts or intent. No provider calls or artifact edits.')
(output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
PY
