"""Analyze all completed diagnostic cells; no outcome-based selection."""
import hashlib,json,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
base=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');source=base/'calls-10376113';result=json.loads((source/'result.json').read_text())
assert result['success'] and not result['failures'] and len(result['results'])==36
rows=result['results'];keys={(r['context'],r['arm'],r['order']):r for r in rows};assert len(keys)==36
by_arm={};review=[]
for arm in ['control','clarification']:
 agree=total=ties=judgments=0;context_counts=[]
 for context in range(9):
  original=keys[context,arm,'original'];swapped=keys[context,arm,'swapped']
  a,b=original['preferences'],swapped['preferences'];assert set(a)==set(b)
  n=sum(a[p]==b[p] for p in a);agree+=n;total+=len(a);ties+=sum(v is None for v in [*a.values(),*b.values()]);judgments+=2*len(a)
  context_counts.append(dict(context=context,agreement=n,total=len(a),discovery_anchor=original['discovery_anchor']))
 by_arm[arm]=dict(order_agreement=agree,pair_comparisons=total,ties=ties,judgments=judgments,contexts=context_counts)
for context in range(9):
 inp=json.loads((base/f'inputs-v1/context-{context:02d}.json').read_text());pair=inp['review_pair'];record={'context':context,'pair_id':pair,'history':inp['history'],'discovery_anchor':inp['discovery_anchor'],'cells':[]}
 for arm in ['control','clarification']:
  for order in ['original','swapped']:
   r=keys[context,arm,order];folder=Path(r['output']);raw=json.loads((folder/f"output-{r['attempts']}.json").read_text());req=json.loads((folder/'request.json').read_text());ev=json.loads(req['evidence']);p=next(p for p in ev['pairs'] if p['pair_id']==pair);response=json.loads(raw['response_text']);assessment=next(a for a in response['assessments'] if a['pair_id']==pair)
   record['cells'].append(dict(arm=arm,order=order,A=p['artifact_A']['artifact_id'],B=p['artifact_B']['artifact_id'],preferred_id=r['preferences'][pair],assessment=assessment,cost=raw['cost']))
 review.append(record)
summary=dict(success=True,job_id=os.environ['SLURM_JOB_ID'],source_sha256=hashlib.sha256((source/'result.json').read_bytes()).hexdigest(),elapsed_seconds=result['elapsed_seconds'],cells=36,retries=sum(r['attempts']-1 for r in rows),by_arm=by_arm,review=review,interpretation='Order agreement is not factual correctness. Context pairs can repeat; no population uncertainty or RH conclusion is implied.')
out=base/'analysis-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(summary,indent=2))
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-pair-attribution-analysis.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='review'},indent=2))
