import json,os,hashlib
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
a=json.loads((b/'comparison-recovered-v3/analysis.json').read_text());seen=set();out=[]
for r in a['rows']:
 k=(r['task_id'],r['replicate'])
 if r['analysis_condition'].split('/')[0]!='active' or k not in {('da-15-1',2),('da-10-1',3)} or k in seen:continue
 seen.add(k);root=Path(r['state_path']).parent
 for p in sorted((root/'rubric-generations').glob('*/evolution.json')):
  raw=p.read_bytes();record=json.loads(raw)
  out.append(dict(task=k[0],replicate=k[1],path=str(p),sha256=hashlib.sha256(raw).hexdigest(),record=record))
large=b/'admission-cases-v1';large.mkdir(exist_ok=False);(large/'records.json').write_text(json.dumps(out,indent=2))
print('records',len(out));print('keys',list(out[0]['record']) if out else [])
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-admission-cases.json').write_text(json.dumps(out,indent=2))
