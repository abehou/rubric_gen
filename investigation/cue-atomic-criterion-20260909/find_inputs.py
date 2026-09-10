import json,hashlib,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');index=json.loads((root/'docs/reports/2026-09-09/cue-pair-context-index.json').read_text());rows=[]
for n in [0,3,4]:
 g=Path(index['contexts'][n]['history']).parent;e=json.loads((g/'evolution.json').read_text());matches=[]
 for p in (g.parent.parent/'rubric-proposer-records').glob('*.json'):
  x=json.loads(p.read_text())
  if x['identity']['context']==e['context'] and x['request']['stage']=='induction' and hashlib.sha256(x['output']['response_text'].encode()).hexdigest()==e['induction_sha256']:matches.append(p)
 assert len(matches)==1
 p=matches[0];parts=g.parts;i=parts.index('experiments');rows.append({'task':parts[i+1],'replicate':parts[i+2],'generation':str(g),'original_request_record':str(p),'request_record_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'provider_contract':e['context']['proposer']})
out=root/'investigation/cue-atomic-criterion-20260909/inputs.json'
with out.open('x') as f:json.dump({'scope':'Three saved corroborated-pair contexts; atomic criterion scope versus fresh control, independent native validation/admission; no revisions','rows':rows},f,indent=2)
print('indexed',len(rows))
