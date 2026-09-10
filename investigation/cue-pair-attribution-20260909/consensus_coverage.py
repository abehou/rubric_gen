"""Counterfactual coverage only; do not mutate or rerun admission."""
import json,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');r=json.loads((b/'calls-10376113/result.json').read_text());assert r['success']
keys={(c['context'],c['order']):c for c in r['results'] if c['arm']=='control'};rows=[]
for n in range(9):
 x=json.loads((b/f'inputs-v1/context-{n:02d}.json').read_text());g=Path(x['history']);comparisons=json.loads((g/'pairwise-comparisons.json').read_text())['comparisons'];a=keys[n,'original']['preferences'];z=keys[n,'swapped']['preferences'];assert set(a)==set(z)
 rows.append({'context':n,'discovery_anchor':x['discovery_anchor'],'history':str(g),'all_assessed':len(a),'order_consistent_nontie':sum(a[k] is not None and a[k]==z[k] for k in a),'historical_comparisons':[{'pair_id':c['pair_id'],'subset':c['subset'],'gap_views':c['gap_views'],'original_preferred':c['preferred_artifact_id'],'new_original':a[c['pair_id']],'new_swapped':z[c['pair_id']],'corroborated':a[c['pair_id']]==z[c['pair_id']]==c['preferred_artifact_id']} for c in comparisons]})
out=b/'consensus-coverage-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(rows,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-consensus-coverage.json').write_text(json.dumps(rows,indent=2));print('contexts',len(rows))
