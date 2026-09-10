import hashlib,json,os
from pathlib import Path
from rubric_gen.submission_revision.evolution_serialization import canonical_json
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');out=b/'ordered-pair-inputs-v1';out.mkdir(exist_ok=False);prepared=[];checks=[]
for n in range(10):
 src=b/f'single-pair-inputs-v1/context-{n:02d}.json';x=json.loads(src.read_text());cells=[]
 for c in x['cells']:
  ev=json.loads(c['evidence']);assert len(ev['pairs'])==1 and len(ev['artifacts'])==2
  pair=ev['pairs'][0];order=[pair['artifact_A']['artifact_id'],pair['artifact_B']['artifact_id']];old=[a['artifact_id'] for a in ev['artifacts']];artifacts={a['artifact_id']:a for a in ev['artifacts']}
  changed={**ev,'artifacts':[artifacts[i] for i in order]};assert {k:v for k,v in ev.items() if k!='artifacts'}=={k:v for k,v in changed.items() if k!='artifacts'}
  assert sorted(changed['artifacts'],key=lambda a:a['artifact_id'])==sorted(ev['artifacts'],key=lambda a:a['artifact_id'])
  checks.append({'context':n,'order':c['order'],'old_table':old,'pair_order':order,'changed':old!=order})
  cells.append({**c,'arm':'ordered_pair','evidence':canonical_json(changed)})
 x={**x,'cells':cells,'source_single_input_sha256':hashlib.sha256(src.read_bytes()).hexdigest()};p=out/f'context-{n:02d}.json';p.write_text(json.dumps(x,indent=2));prepared.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
r={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'calls':20,'requests':prepared,'order_checks':checks};(out/'acceptance.json').write_text(json.dumps(r,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-ordered-pair-acceptance.json').write_text(json.dumps(r,indent=2));print('validated20cells; changed',sum(c['changed'] for c in checks))
