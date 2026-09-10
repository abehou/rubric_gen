import json,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');r=json.loads((b/'ordered-calls-10376310/result.json').read_text());old=json.loads((b/'single-calls-10376267/result.json').read_text());assert r['success'] and len(r['results'])==20 and old['success']
new={(c['context'],c['order']):c for c in r['results']};controls={(c['context'],c['order']):c for c in old['results'] if c['arm']=='single_pair'};assert len(new)==20
rows=[]
for n in range(10):
 inp=json.loads((b/f'single-pair-inputs-v1/context-{n:02d}.json').read_text());pair=inp['review_pair'];row={'context':n,'pair_id':pair,'discovery_anchor':n>=8,'cells':[]}
 for arm in ['single','ordered']:
  for order in ['original','swapped']:
   c=controls[n,order] if arm=='single' else new[n,order];p=Path(c['output']);response=json.loads(json.loads((p/f"output-{c['attempts']}.json").read_text())['response_text']);ev=json.loads(json.loads((p/'request.json').read_text())['evidence']);pr=next(a for a in ev['pairs'] if a['pair_id']==pair)
   row['cells'].append({'arm':arm,'order':order,'preferred_id':c['preferences'][pair],'A':pr['artifact_A']['artifact_id'],'B':pr['artifact_B']['artifact_id'],'assessment':next(a for a in response['assessments'] if a['pair_id']==pair)})
 rows.append(row)
summary={}
for arm in ['single','ordered']:
 groups=[[c for c in row['cells'] if c['arm']==arm] for row in rows];summary[arm]={'agreement':sum(g[0]['preferred_id']==g[1]['preferred_id'] for g in groups),'pairs':10,'ties':sum(c['preferred_id'] is None for g in groups for c in g),'nonanchor_agreement':sum(g[0]['preferred_id']==g[1]['preferred_id'] for g in groups[:8])}
x={'success':True,'job_id':os.environ['SLURM_JOB_ID'],'elapsed_seconds':r['elapsed_seconds'],'new_calls':20,'retries':sum(c['attempts']-1 for c in r['results']),'summary':summary,'rows':rows,'caveat':'Earlier single-pair controls reused; half ordered requests repeat unchanged inputs. Small enriched diagnostic, not RH or population accuracy evidence.'};out=b/'ordered-analysis-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(x,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-ordered-pair-result.json').write_text(json.dumps(x,indent=2));print(json.dumps(summary))
