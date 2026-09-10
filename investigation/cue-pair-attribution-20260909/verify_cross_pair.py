import json,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');x=json.loads((b/'inputs-v1/context-08.json').read_text());ev=json.loads(x['cells'][0]['evidence']);pair=next(p for p in ev['pairs'] if p['pair_id']=='pair_de407f0626f0d526')
ids=[pair['artifact_A']['artifact_id'],pair['artifact_B']['artifact_id'],'artifact_8442669919b645a5'];rows=[]
for a in ev['artifacts']:
 if a['artifact_id'] in ids:
  rows.append({'artifact_id':a['artifact_id'],'lines':[{'line':i,'text':s} for i,s in enumerate(a['content'].splitlines(),1) if any(t in s for t in ['retained','58,884','188','18,','filter'])]})
r={'job_id':os.environ['SLURM_JOB_ID'],'pair':pair,'artifacts':rows,'schema':x['cells'][0]['schema']};out=b/'cross-pair-verification-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(r,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-cross-pair-verification.json').write_text(json.dumps(r,indent=2));print('verified source extraction')
