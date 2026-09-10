"""Recover exact cached pair assessments and validate every diagnostic mutation."""
import hashlib,json,os
from pathlib import Path
from transforms import CLARIFICATION,swap
from rubric_gen.submission_revision.evolution_assessment import AssessmentView,assessment_instructions,pair_text_difference
from rubric_gen.submission_revision.evolution_serialization import canonical_json,canonical_sha256
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');src=root/'docs/reports/2026-09-09/cue-pair-context-index.json';index=json.loads(src.read_text())
out=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909/inputs-v1');out.mkdir(parents=True,exist_ok=False)
prepared=[]
for n,c in enumerate(index['contexts']):
 g=Path(c['history']).parent;generation=json.loads((g/'evolution.json').read_text());matches=[]
 for p in (g.parent.parent/'rubric-proposer-records').glob('*.json'):
  x=json.loads(p.read_text())
  if x['identity']['context']!=generation['context'] or x['request']['stage']!='assessment_rubric_free':continue
  if hashlib.sha256(x['output']['response_text'].encode()).hexdigest()!=generation['assessment_rubric_free_sha256']:continue
  assert canonical_sha256(x['output'])==x['output_sha256']
  assert p.stem==canonical_sha256({'identity':x['identity'],'request':x['request']})
  matches.append((p,x))
 assert len(matches)==1,(str(g),len(matches))
 p,x=matches[0];request=x['request'];ev=json.loads(request['evidence']);assert canonical_json(ev)==request['evidence']
 sw=swap(request['evidence']);assert swap(canonical_json(sw))==ev
 arts={a['artifact_id']:a['content'] for a in ev['artifacts']}
 for pair in sw['pairs']:assert pair['visible_difference']==pair_text_difference(arts[pair['artifact_A']['artifact_id']],arts[pair['artifact_B']['artifact_id']])
 instructions=assessment_instructions(AssessmentView.RUBRIC_FREE)
 cells=[]
 for arm in ['control','clarification']:
  for order in ['original','swapped']:
   cells.append({'arm':arm,'order':order,'instructions':instructions+ ('\n'+CLARIFICATION if arm=='clarification' else ''),'evidence':request['evidence'] if order=='original' else canonical_json(sw),'schema':request['response_schema'],'contract':generation['context']['proposer']})
 record={'context':n,'history':str(g),'source_cache':str(p),'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source_identity':x['identity'],'discovery_anchor':c['pair_id']=='pair_c94a2cf8125fe4dc','review_pair':c['pair_id'],'cells':cells}
 f=out/f'context-{n:02d}.json';f.write_text(json.dumps(record,indent=2));prepared.append({'path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'pairs':len(ev['pairs']),'contract':generation['context']['proposer']})
receipt={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'contexts':len(prepared),'calls':4*len(prepared),'source_index_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'requests':prepared,'provider_calls':0}
(out/'acceptance.json').write_text(json.dumps(receipt,indent=2));(root/'docs/reports/2026-09-09/cue-pair-attribution-acceptance.json').write_text(json.dumps(receipt,indent=2));print('validated',len(prepared),'contexts',len(prepared)*4,'cells')
