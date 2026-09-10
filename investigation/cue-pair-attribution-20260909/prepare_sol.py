"""Authorized model-only comparison, original full-context pair assessments."""
import hashlib,json,os
from pathlib import Path
from rubric_gen.submission_revision.evolution_provider import ProviderContract
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');out=b/'sol-inputs-v1';out.mkdir(exist_ok=False);prepared=[]
for n in range(9):
 src=b/f'inputs-v1/context-{n:02d}.json';x=json.loads(src.read_text());cells=[]
 for c in x['cells']:
  if c['arm']!='control':continue
  assert c['contract']['model']=='gpt-5.6-luna'
  contract={**c['contract'],'model':'gpt-5.6-sol'}
  native=ProviderContract(**{k:contract[k] for k in ['model','max_output_tokens','max_request_bytes','service_tier']});assert native.record()==contract
  changed={**c,'arm':'sol','contract':contract}
  assert {k:v for k,v in c.items() if k not in ['arm','contract']}=={k:v for k,v in changed.items() if k not in ['arm','contract']}
  cells.append(changed)
 assert len(cells)==2
 x={**x,'cells':cells,'source_input_sha256':hashlib.sha256(src.read_bytes()).hexdigest()};p=out/f'context-{n:02d}.json';p.write_text(json.dumps(x,indent=2));prepared.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
r={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'calls':18,'requests':prepared,'sole_scientific_change':'rubric-free induction pair assessment model gpt-5.6-luna to gpt-5.6-sol; all settings and full contexts unchanged'};(out/'acceptance.json').write_text(json.dumps(r,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-sol-acceptance.json').write_text(json.dumps(r,indent=2));print('validated18model-onlycells',flush=True)
