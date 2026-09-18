from __future__ import annotations
import json, os
from pathlib import Path
TASKS = (
'da-8-1','da-26-4','da-20-4','da-19-3','da-4-1','da-1-3','da-3-5','da-4-6','da-5-1','da-26-2',
'da-9-7','da-24-3','da-6-5','da-17-3','da-1-4','da-8-3','da-17-5','da-17-1','da-9-1','da-20-1')
Q6=Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results30')
Q7=Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results45-added15')
rows=[]
for i,task in enumerate(TASKS):
 root=(Q6 if i<10 else Q7)/task
 files=[]
 for rel in ('inputs/seeds','inputs/paraphrases','study','audit'):
  p=root/rel
  item={'path':str(p),'exists':p.exists(),'is_dir':p.is_dir()}
  if p.is_dir():
   item['files']=sum(1 for q in p.rglob('*') if q.is_file())
   item['bytes']=sum(q.stat().st_size for q in p.rglob('*') if q.is_file())
   item['top']=[str(q.relative_to(p)) for q in sorted(p.rglob('*')) if q.is_file()][:30]
  files.append(item)
 rows.append({'task':task,'root':str(root),'root_exists':root.is_dir(),'components':files})
out={'job_id':os.environ['SLURM_JOB_ID'],'tasks':rows}
p=Path('experiments/trace-v21-execution-verified-provenance-result40/receipts/initial-inventory.json')
p.write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'job_id':out['job_id'],'tasks':len(rows),'roots':sum(r['root_exists'] for r in rows),'seed_files':sum(r['components'][0].get('files',0) for r in rows),'paraphrase_files':sum(r['components'][1].get('files',0) for r in rows),'study_files':sum(r['components'][2].get('files',0) for r in rows)},indent=2))
