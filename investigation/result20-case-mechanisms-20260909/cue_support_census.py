"""Read-only census of saved criterion admission; no calls or counterfactual outcomes."""
from pathlib import Path
import collections, hashlib, json, os
ROOT=Path('/home/aydanh/repos/rubric_gen')
BASE=ROOT/'runs/babel-result20-cue-contrast-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3'
def main():
 if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm required for full saved-corpus census')
 rows=[];counts=collections.Counter();sources={};generations=0
 def read(p):
  b=p.read_bytes();sources[str(p)]=hashlib.sha256(b).hexdigest();return json.loads(b)
 for p in sorted(BASE.glob('experiments/*/rep-*/luna/*/rubric-generations/generation-*/aggregate-margins.json')):
  g=p.parent
  if g.name=='generation-0000':continue # Shared starting induction is not an online update.
  d=read(p);generations+=1
  if not d['decisions']:continue
  proposals=read(g/'criterion-proposal.json')['criteria'];valid=read(g/'criterion-validation.json')['validations'];pairs={c['pair_id']:c for c in read(g/'pairwise-comparisons.json')['comparisons']}
  assert len(proposals)==len(valid)==len(d['decisions'])
  for prop,v,dec in zip(proposals,valid,d['decisions'],strict=True):
   assert v['criterion_id']==dec['criterion_id']
   levels={x['artifact_id']:x['level'] for x in v['artifact_applications']}
   order={x['label']:i for i,x in enumerate(prop['levels'])}
   supports=[]
   for pid in prop['provenance_pair_ids']:
    pair=pairs[pid];a=levels[pair['preferred_artifact_id']];b=levels[pair['rejected_artifact_id']]
    relation='supports' if order[a]<order[b] else 'tie' if order[a]==order[b] else 'inversion'
    supports.append(dict(pair_id=pid,preferred_level=a,rejected_level=b,relation=relation))
   dist=collections.Counter(x['relation'] for x in supports)
   row=dict(path=str(g),criterion_id=v['criterion_id'],title=prop['title'],requirement=prop['requirement'],replaces=prop.get('replaces',[]),decision=dec['reason'],observable=v['observable'],nonredundant=v['nonredundant'],support_counts=dict(dist),pairs=supports)
   rows.append(row);counts[dec['reason']]+=1
   if dec['reason']=='criterion_support_failed' and dist['supports'] and dist['tie'] and not dist['inversion'] and not prop.get('replaces'):
    counts['support_failed_positive_plus_ties_no_replacement']+=1
 out=ROOT/'docs/reports/2026-09-09';payload=dict(job_id=os.environ['SLURM_JOB_ID'],scope='online generations only; no generation-0000',generations=generations,counts=dict(counts),rows=rows,source_hashes=sources)
 for suffix in ['json','md']:
  if (out/f'rubric-cue-support-census.{suffix}').exists():raise FileExistsError('preserve previous analysis')
 (out/'rubric-cue-support-census.json').write_text(json.dumps(payload,indent=2)+'\n')
 lines=['# Rubric-cue online criterion-support census','','Saved completed Result20 trace only. Excludes shared generation0000. No provider calls, no changed admission, no counterfactual behavioral claims.',f'Job: {os.environ["SLURM_JOB_ID"]}; generations: {generations}; candidates: {len(rows)}.','','| Category | Count |','|---|---:|']
 lines += [f'| {k} | {v} |' for k,v in sorted(counts.items())]
 lines += ['','A supported pair plus cited ties can indicate overbroad provenance, but this census does not prove a candidate would pass unchanged aggregate-margin/replacement checks or improve solver behavior. Inversions remain distinct. Do not loosen admission or launch a policy from these counts alone. Full identities and source hashes are in the adjacent JSON.','']
 (out/'rubric-cue-support-census.md').write_text('\n'.join(lines));print('\n'.join(lines))
if __name__=='__main__':main()
