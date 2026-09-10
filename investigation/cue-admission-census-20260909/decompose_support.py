"""Decompose support failures without changing any candidate or gate."""
from pathlib import Path
from collections import Counter
import hashlib,json,os,sys
assert os.environ.get('SLURM_JOB_ID')
ROOT=Path('/home/aydanh/repos/rubric_gen');sys.path.insert(0,str(ROOT/'investigation/cue-citation-diagnostic-20260909'))
from context import load_context,ep
receipt=json.loads((ROOT/'docs/reports/2026-09-09/cue-admission-census.json').read_text());src=Path(receipt['analysis_path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==receipt['analysis_sha256'];source=json.loads(src.read_text());rows=[];counts=Counter()
for record in source['rows']:
 if record['context']['policy']!='red_team_trace' or not record['candidates']:continue
 x=load_context({'path':record['path']});active={c.criterion_id:c for c in x['current'].elicited_criteria};pairs={p.pair_id:p for p in x['pairs']};_,decisions=ep.admit_candidates(x['candidates'],x['validations'],x['pairs'],x['current'])
 for c,v,d in zip(x['candidates'],x['validations'],decisions,strict=True):
  points=ep._candidate_application_points(c,v)
  def assess(ids):
   result=[]
   for pid in dict.fromkeys(ids):
    if pid not in pairs:result.append({'pair_id':pid,'status':'missing_pair'});continue
    p=pairs[pid];a=points[p.preferred_artifact_id];b=points[p.rejected_artifact_id];result.append({'pair_id':pid,'status':'supported' if a>b else 'tie' if a==b else 'reversed','preferred_points':a,'rejected_points':b,'preferred':p.preferred_artifact_id,'rejected':p.rejected_artifact_id})
   return result
  own=assess(c.criterion.provenance_pair_ids);inherited=assess(pid for cid in c.replaces for pid in active[cid].provenance_pair_ids);own_ok=all(v['status']=='supported' for v in own);inherited_ok=all(v['status']=='supported' for v in inherited)
  if d.reason=='criterion_support_failed':assert not(own_ok and inherited_ok)
  if d.reason in {'accepted','aggregate_margin_failed'}:assert own_ok and inherited_ok
  category='both_pass' if own_ok and inherited_ok else 'inherited_only_failure' if own_ok else 'own_only_failure' if inherited_ok else 'own_and_inherited_failure'
  counts[d.reason+':'+category]+=1
  rows.append({'path':record['path'],'task':record['task'],'replicate':record['replicate'],'criterion_id':c.criterion.criterion_id,'title':c.criterion.title,'reason':d.reason,'replaces':list(c.replaces),'own':own,'inherited':inherited,'category':category})
assert len(rows)==395
out=src.parent/'support-decomposition-v1';out.mkdir(exist_ok=False);r={'job_id':os.environ['SLURM_JOB_ID'],'source_sha256':receipt['analysis_sha256'],'counts':dict(counts),'rows':rows};(out/'analysis.json').write_text(json.dumps(r,indent=2));(ROOT/'docs/reports/2026-09-09/cue-support-decomposition.json').write_text(json.dumps(r,indent=2));print('candidates',len(rows));print(dict(counts))
