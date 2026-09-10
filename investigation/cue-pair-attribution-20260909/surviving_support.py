import json,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');source=json.loads((b/'consensus-coverage-v1/analysis.json').read_text());out=[]
for r in source:
 keep={c['pair_id']:c for c in r['historical_comparisons'] if c['corroborated'] and c['gap_views'] and c['subset']=='induction'}
 if not keep:continue
 g=Path(r['history']);proposals=json.loads((g/'criterion-proposal.json').read_text())['criteria'];validations=json.loads((g/'criterion-validation.json').read_text())['validations'];decisions=json.loads((g/'aggregate-margins.json').read_text())['decisions'];assert len(proposals)==len(validations)==len(decisions)
 cs=[]
 for p,v,d in zip(proposals,validations,decisions):
  cited=set(p['provenance_pair_ids'])&set(keep)
  if cited:cs.append({'proposal':p,'validation':v,'admission':d,'corroborated_citations':sorted(cited)})
 out.append({'context':r['context'],'history':str(g),'surviving_pairs':list(keep.values()),'proposals_total':len(proposals),'candidates':cs})
dest=b/'surviving-support-v1';dest.mkdir(exist_ok=False);(dest/'analysis.json').write_text(json.dumps(out,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-surviving-support.json').write_text(json.dumps(out,indent=2));print('surviving contexts',len(out),'citing candidates',sum(len(r['candidates']) for r in out))
