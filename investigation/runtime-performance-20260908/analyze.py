"""Read-only runtime accounting across immutable Result20 dispatcher receipts."""
import json,hashlib,os
from pathlib import Path
root=Path('runs/babel-overnight-20260907')
rows=[]
for owner in sorted(root.glob('dispatcher-*-result20*')):
 for p in sorted(owner.glob('*/launch.json')):
  launch=json.loads(p.read_text()); receipt=p.parent
  metrics=receipt/'metrics.jsonl'; samples=[]
  if metrics.exists():
   for line in metrics.read_text().splitlines():
    try:samples.append(json.loads(line))
    except json.JSONDecodeError:continue
  result=receipt/'result.json'
  stages={}
  for stage in ['revise','detect']:
   cmd=receipt/f'{stage}-command.json'
   if cmd.exists():stages[stage]=json.loads(cmd.read_text())
  last=samples[-1] if samples else {}
  # Counters may restart at stage transitions: do not sum cumulative samples.
  rows.append(dict(job=launch.get('job_id'),receipt=str(receipt),source=launch.get('git_commit'),resources=launch.get('resource_request'),workers=launch.get('workers'),audit_workers=launch.get('audit_workers'),stages=stages,result=json.loads(result.read_text()) if result.exists() else None,samples=len(samples),last=last,max_active_slots=max((s.get('active_provider_slots',0) for s in samples),default=0),peak_sampled_rss_kib=max((s.get('peak_sampled_rss_kib',0) for s in samples),default=0),peak_processes=max((s.get('peak_processes',0) for s in samples),default=0),peak_sampled_cpu=max((s.get('sampled_cpu_cores',0) or 0 for s in samples),default=0),launch_sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
out=Path(f'runs/runtime-performance-{os.environ["SLURM_JOB_ID"]}');out.mkdir(exist_ok=False)
(out/'summary.json').write_text(json.dumps(dict(scope='Cumulative counters shown per receipt, not summed across snapshots; overlapping jobs are not additive wall time; sampled maxima are lower bounds.',rows=rows,script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n')
for r in rows:print(json.dumps({k:r[k] for k in ['job','source','samples','max_active_slots','peak_sampled_rss_kib','peak_processes','peak_sampled_cpu','result']}))
