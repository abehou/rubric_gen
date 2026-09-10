"""Read-only canonical semantic-flag disagreement census; never change gates."""
from pathlib import Path
from collections import Counter,defaultdict
import hashlib,json,os,sys
assert os.environ.get('SLURM_JOB_ID')
ROOT=Path('/home/aydanh/repos/rubric_gen');sys.path.insert(0,str(ROOT/'investigation/cue-citation-diagnostic-20260909'))
from context import load_context,ep,ea
from rubric_gen.submission_revision.evolution_serialization import canonical_sha256
receipt=json.loads((ROOT/'docs/reports/2026-09-09/cue-admission-census.json').read_text());p=Path(receipt['analysis_path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==receipt['analysis_sha256'];source=json.loads(p.read_text());cache={};rows=[];counts=Counter();invalid_records=[];retry_records=[]
for row in source['rows']:
 if row['context']['policy']!='red_team_trace' or not row['candidates']:continue
 g=Path(row['path']);root=g.parents[1]
 if root not in cache:
  by_round=defaultdict(list)
  for rp in (root/'rubric-proposer-records').glob('*.json'):
   record=json.loads(rp.read_text())
   if record['request']['stage']=='validation':by_round[record['identity']['context']['generation_round']].append((rp,record))
  cache[root]=by_round
 x=load_context({'path':str(g)});parts=defaultdict(list);template=None
 for rp,record in cache[root][x['n']]:
  assert canonical_sha256(record['output'])==record['output_sha256']
  e,end=json.JSONDecoder().raw_decode(record['request']['evidence']);suffix=record['request']['evidence'][end:].strip()
  if suffix:retry_records.append({'path':str(rp),'suffix_sha256':hashlib.sha256(suffix.encode()).hexdigest(),'suffix_bytes':len(suffix.encode())})
  assert len(e['artifacts'])==1
  base={k:v for k,v in e.items() if k!='artifacts'}
  if template is None:template=base
  assert template==base
  aid=e['artifacts'][0]['artifact_id']
  try:values=ep.validated_validation_response(record['output']['response_text'],candidates=x['candidates'],artifact_ids=(aid,))
  except ValueError as error:
   invalid_records.append({'path':str(rp),'error':str(error)});continue
  saved_values={v.criterion_id:v for v in x['validations']}
  for v in values:
   saved_app=next(a for a in saved_values[v.criterion_id].artifact_applications if a.artifact_id==aid)
   assert v.artifact_applications[0]==saved_app, 'cached response differs from frozen generation application'
  for v in values:parts[v.criterion_id].append({'artifact_id':aid,'observable':v.observable,'nonredundant':v.nonredundant,'reason':v.reason,'request_path':str(rp),'record_sha256':hashlib.sha256(rp.read_bytes()).hexdigest()})
 for c,v,d in zip(x['candidates'],x['validations'],row['decisions'],strict=True):
  members=parts[c.criterion.criterion_id];assert {m['artifact_id'] for m in members}==set(ea.validation_artifact_ids(x['pairs']));assert len(members)==len({m['artifact_id'] for m in members})
  assert all(m['observable'] for m in members)==v.observable and all(m['nonredundant'] for m in members)==v.nonredundant
  mixed_obs=len({m['observable'] for m in members})>1;mixed_nr=len({m['nonredundant'] for m in members})>1
  counts['candidates']+=1;counts['mixed_observable']+=mixed_obs;counts['mixed_nonredundant']+=mixed_nr
  if d['reason']=='semantic_validation_failed':
   counts['semantic_failures']+=1;counts['semantic_failure_mixed_observable']+=mixed_obs;counts['semantic_failure_mixed_nonredundant']+=mixed_nr
   counts['semantic_failure_one_nonredundant_veto']+=sum(not m['nonredundant'] for m in members)==1
  rows.append({'task':row['task'],'replicate':row['replicate'],'generation':x['n'],'criterion_id':c.criterion.criterion_id,'reason':d['reason'],'observable':v.observable,'nonredundant':v.nonredundant,'members':members})
assert len(rows)==395 and counts['semantic_failures']==39
out=Path('/data/user_data/aydanh/rubric_gen/runs')/f"cue-semantic-census-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False);result={'job_id':os.environ['SLURM_JOB_ID'],'source_sha256':receipt['analysis_sha256'],'counts':dict(counts),'rows':rows,'invalid_cached_records':invalid_records,'retry_prompt_records':retry_records};(out/'analysis.json').write_text(json.dumps(result,indent=2));small={'job_id':result['job_id'],'source_sha256':result['source_sha256'],'counts':result['counts'],'invalid_cached_records':len(invalid_records),'retry_prompt_records':len(retry_records),'analysis_path':str(out/'analysis.json'),'analysis_sha256':hashlib.sha256((out/'analysis.json').read_bytes()).hexdigest()};(ROOT/'docs/reports/2026-09-09/cue-semantic-census.json').write_text(json.dumps(small,indent=2));print(json.dumps(small))
