import json,os,hashlib
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');base=Path('/data/user_data/aydanh/rubric_gen/runs');run=base/'cue-application-check-10377405';r=json.loads((run/'result.json').read_text());assert r['success'] and len(r['results'])==9
inputs=json.loads((root/'investigation/cue-sol-supervision-20260909/inputs.json').read_text());index={(v['task'],v['replicate']):v for v in inputs['rows']};rows=[]
for c in r['results']:
 row=index[(c['task'],c['replicate'])]
 path=(base/'cue-pair-attribution-20260909/sol-gap-impact-v1'/f"context-{row['context']:02d}.json") if c['arm']=='numerical_check' else Path(row['generation'])/'pairwise-comparisons.json'
 d=json.loads(path.read_text());raw=d['comparisons']['comparisons'] if c['arm']=='numerical_check' else d['comparisons'];pairs={v['pair_id']:v for v in raw}
 vals={v['criterion_id']:v for v in c.get('validations',{}).get('validations',[])}
 for cand,decision in zip(c.get('candidates',[]),c['decisions'],strict=True):
  cr=cand['criterion'];val=vals[cr['criterion_id']];apps={a['artifact_id']:a for a in val['artifact_applications']};e=[]
  for pairid in sorted(set(cr['provenance_pair_ids'])|{m['pair_id'] for m in decision['margin_checks'] if not m['passed']}):
   p=pairs[pairid];e.append({'pair':p,'cited':pairid in cr['provenance_pair_ids'],'preferred_application':apps[p['preferred_artifact_id']],'rejected_application':apps[p['rejected_artifact_id']]})
  rows.append({'context':row['context'],'task':c['task'],'replicate':c['replicate'],'arm':c['arm'],'criterion':cr,'decision':decision,'semantic_validation':{k:v for k,v in val.items() if k!='artifact_applications'},'pairs':e})
out=run/'support-analysis-v1';out.mkdir(exist_ok=False);result={'job_id':os.environ['SLURM_JOB_ID'],'source_sha256':hashlib.sha256((run/'result.json').read_bytes()).hexdigest(),'rows':rows};(out/'analysis.json').write_text(json.dumps(result,indent=2));(root/'docs/reports/2026-09-09/cue-application-check-support.json').write_text(json.dumps(result,indent=2));print('candidate rows',len(rows))
