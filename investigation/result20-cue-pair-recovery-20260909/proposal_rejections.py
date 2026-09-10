import os,json,hashlib
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');base=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
source=json.loads((root/'docs/reports/2026-09-09/cue-admission-cases.json').read_text());rows=[]
for r in source:
 g=Path(r['path']).parent;files={}
 for name in ['criterion-proposal.json','criterion-validation.json','aggregate-margins.json']:
  p=g/name;raw=p.read_bytes();files[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),data=json.loads(raw))
 rows.append(dict(task=r['task'],replicate=r['replicate'],generation=g.name,path=str(g),files=files))
p=base/'proposal-rejections-v1';p.mkdir(exist_ok=False);(p/'analysis.json').write_text(json.dumps(rows,indent=2))
(root/'docs/reports/2026-09-09/cue-proposal-rejections.json').write_text(json.dumps(rows,indent=2))
print('generations',len(rows))
