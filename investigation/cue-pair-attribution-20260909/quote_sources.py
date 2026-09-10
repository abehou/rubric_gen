"""Literal quote attribution inventory, with no inferred scientific gold labels."""
import json,os,re
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');r=json.loads((b/'calls-10376113/result.json').read_text());checks=[]
for cell in r['results']:
 p=Path(cell['output']);ev=json.loads(json.loads((p/'request.json').read_text())['evidence']);arts={a['artifact_id']:a['content'] for a in ev['artifacts']};pairs={a['pair_id']:a for a in ev['pairs']}
 response=json.loads(json.loads((p/f"output-{cell['attempts']}.json").read_text())['response_text'])
 for assessment in response['assessments']:
  pair=pairs[assessment['pair_id']]
  for letter in ['A','B']:
   aid=pair['artifact_'+letter]['artifact_id'];reason=assessment['assessment_'+letter]
   for quote in re.findall(r'“([^”]+)”|"([^"\n]+)"',reason):
    q=next(s for s in quote if s)
    if len(q)<4:continue
    matches=[i for i,text in arts.items() if q in text]
    checks.append(dict(context=cell['context'],arm=cell['arm'],order=cell['order'],pair_id=assessment['pair_id'],letter=letter,artifact_id=aid,quote=q,own_match=aid in matches,matching_artifact_ids=matches,reason=reason))
out=b/'quote-sources-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(checks,indent=2))
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-pair-quote-sources.json').write_text(json.dumps(checks,indent=2));print('literal quotes',len(checks),'own text absent',sum(not c['own_match'] for c in checks))
