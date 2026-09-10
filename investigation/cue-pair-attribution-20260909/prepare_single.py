import copy,hashlib,json,os
from pathlib import Path
from transforms import swap
from rubric_gen.submission_revision.evolution_serialization import canonical_json
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');out=b/'single-pair-inputs-v1';out.mkdir(exist_ok=False);prepared=[]
for n in range(10):
 source=b/f'inputs-v1/context-{min(n,8):02d}.json';x=json.loads(source.read_text());pair=x['review_pair'] if n<9 else 'pair_de407f0626f0d526';cells=[]
 for c in x['cells']:
  if c['arm']!='control':continue
  ev=json.loads(c['evidence']);selected=next(p for p in ev['pairs'] if p['pair_id']==pair);ids={selected['artifact_A']['artifact_id'],selected['artifact_B']['artifact_id']}
  isolated=copy.deepcopy(ev);isolated['pairs']=[selected];isolated['artifacts']=[a for a in ev['artifacts'] if a['artifact_id'] in ids];assert len(isolated['artifacts'])==2
  assert swap(canonical_json(swap(canonical_json(isolated))))==isolated
  schema=copy.deepcopy(c['schema']);items=schema['properties']['assessments'];items['minItems']=items['maxItems']=1;items['items']['properties']['pair_id']['enum']=[pair]
  cells.append({**c,'arm':'single_pair','evidence':canonical_json(isolated),'schema':schema})
 assert len(cells)==2
 record={**x,'context':n,'source_context':min(n,8),'review_pair':pair,'discovery_anchor':n>=8,'cells':cells,'original_input_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
 p=out/f'context-{n:02d}.json';p.write_text(json.dumps(record,indent=2));prepared.append({'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
r={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'calls':20,'requests':prepared,'reused_control_job':'10376113'};(out/'acceptance.json').write_text(json.dumps(r,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-single-pair-acceptance.json').write_text(json.dumps(r,indent=2));print('validated20cells')
