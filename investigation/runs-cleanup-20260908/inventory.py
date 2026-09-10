"""Inventory run storage and regenerable caches without mutating experiment data."""
import json,os,time
from pathlib import Path
root=Path.cwd();rows=[];caches=[]
protected={'.runtime-babel','babel-code','babel-overnight-20260907','babel-result20-current-20260908','babel-result20-capacity-v3-20260908'}
for p in sorted((root/'runs').iterdir()):
 if not p.is_dir():continue
 count=size=0
 for folder,dirs,files in os.walk(p,followlinks=False):
  for name in files:
   q=Path(folder)/name
   try:size+=q.lstat().st_size;count+=1
   except FileNotFoundError:continue
  for d in dirs:
   q=Path(folder)/d
   if d in {'__pycache__','.pytest_cache'} and p.name not in protected and not q.is_symlink():caches.append(str(q))
 role=('active runtime/source/provenance' if p.name in protected else
       'shared reproducibility inputs' if p.name in {'autonomous-dev3-20260907','babel-dev3-da18-inputs-20260908','babel-result20-input-restore-10356965'} else
       'important historical/control evidence' if p.name in {'static-neutral-20260907','selected-reference-wiring-smoke-20260907-attempt02','biomnibench-redteam-2026-09-05','biomnibench-results20-2026-09-06'} else
       'diagnostic acceptance evidence' if any(t in p.name for t in ['telemetry','compaction','runtime-performance','readiness']) else
       'exploratory or infrastructure evidence; review before removal')
 rows.append(dict(path=str(p.relative_to(root)),files=count,bytes=size,role=role,decision='retain',reason='Preserve raw evidence and path-bound provenance until canonical result and detailed dependency review',records=['EXPERIMENT_RUNS.md','EXPERIMENT_LOG.md']))
out=root/'investigation/runs-cleanup-20260908/inventory.json';out.write_text(json.dumps(dict(job=os.environ['SLURM_JOB_ID'],timestamp=time.time(),directories=rows,cache_candidates=caches),indent=2)+'\n')
print(json.dumps(dict(directories=len(rows),bytes=sum(r['bytes'] for r in rows),cache_candidates=len(caches))))
