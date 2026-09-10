"""Read-only primary Result20 admission census and protected bundle feasibility."""
from pathlib import Path
from itertools import combinations
from collections import Counter
import hashlib,json,os,sys
assert os.environ.get('SLURM_JOB_ID')
ROOT=Path('/home/aydanh/repos/rubric_gen');sys.path.insert(0,str(ROOT/'investigation/cue-citation-diagnostic-20260909'))
from context import load_context,ep
BASE=ROOT/'runs/babel-result20-cue-contrast-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments'
roots=sorted(BASE.glob('*/rep-*/luna/user-simulator-red-team-trace'));assert len(roots)==60
rows=[];counts=Counter();skipped=[]
for root in roots:
 for g in sorted(root.glob('rubric-generations/generation-*')):
  if g.name=='generation-0000':continue
  x=load_context({'path':str(g)})
  metadata=json.loads((g/'evolution.json').read_text());context=metadata['context'];mode=context['policy']
  old,decisions=ep.admit_candidates(x['candidates'],x['validations'],x['pairs'],x['current'])
  eligible=[c for c,d in zip(x['candidates'],decisions,strict=True) if d.reason in {'accepted','aggregate_margin_failed'}]
  accepted_ids={c.criterion.criterion_id for c in old};validations={v.criterion_id:v for v in x['validations']};active={c.criterion_id:c for c in x['current'].elicited_criteria};bundles=[]
  if len(eligible)>10:skipped.append(str(g))
  elif mode=='red_team_trace':
   for size in range(max(2,len(old)+1),len(eligible)+1):
    for subset in combinations(eligible,size):
     ids={c.criterion.criterion_id for c in subset}
     if not accepted_ids<=ids:continue
     checks=ep._aggregate_margin_checks(candidates=subset,validations_by_id=validations,comparisons=x['pairs'],active_by_id=active)
     if all(c.passed for c in checks):bundles.append({'candidate_ids':[c.criterion.criterion_id for c in subset],'new_ids':sorted(ids-accepted_ids),'checks':[c.as_dict() for c in checks]})
  record={'path':str(g),'task':root.parents[2].name,'replicate':root.parents[1].name,'generation':x['n'],'context':context,'manifest_sha256':hashlib.sha256((g/'manifest.json').read_bytes()).hexdigest(),'candidates':[c.as_dict() for c in x['candidates']],'decisions':[d.as_dict() for d in decisions],'validations':[{'criterion_id':v.criterion_id,'observable':v.observable,'nonredundant':v.nonredundant} for v in x['validations']],'induction_pairs':len(x['induction']),'comparison_pairs':len(x['pairs']),'protected_bundles':bundles}
  rows.append(record);counts['generations']+=1;counts['candidates']+=len(decisions);counts['accepted_candidates']+=len(old);counts['bundle_gain_contexts']+=bool(bundles)
  for d in decisions:counts[d.reason]+=1
 print('assignments',len({(r['task'],r['replicate']) for r in rows}),'generations',len(rows),flush=True)
out=Path('/data/user_data/aydanh/rubric_gen/runs')/f"cue-admission-census-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False)
r={'job_id':os.environ['SLURM_JOB_ID'],'source_root':str(BASE),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'assignments':len(roots),'counts':dict(counts),'bundle_enumeration_skipped':skipped,'rows':rows}
(out/'analysis.json').write_text(json.dumps(r,indent=2))
receipt={k:v for k,v in r.items() if k!='rows'};receipt['analysis_path']=str(out/'analysis.json');receipt['analysis_sha256']=hashlib.sha256((out/'analysis.json').read_bytes()).hexdigest()
receipt['rows']=[{'path':v['path'],'task':v['task'],'replicate':v['replicate'],'generation':v['generation'],'policy':v['context']['policy'],'candidate_count':len(v['candidates']),'candidate_ids':[c['criterion']['criterion_id'] for c in v['candidates']],'decisions':[{'criterion_id':d['criterion_id'],'accepted':d['accepted'],'reason':d['reason']} for d in v['decisions']],'protected_bundles':[{'candidate_ids':b['candidate_ids'],'new_ids':b['new_ids']} for b in v['protected_bundles']]} for v in rows]
(ROOT/'docs/reports/2026-09-09/cue-admission-census.json').write_text(json.dumps(receipt,indent=2));print(dict(counts));print('skipped enumeration',len(skipped))
