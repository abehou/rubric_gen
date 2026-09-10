"""Compare exact saved candidate applications and fixed repair eligibility."""
from pathlib import Path
from dataclasses import replace
import hashlib,json,collections,os
from diagnostic import prepare,ep,ea
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent;BASE=ROOT/'runs/cue-validation-repeat-10370858'
assert os.environ.get('SLURM_JOB_ID')
result=json.loads((BASE/'result.json').read_text());assert result['success'] and result['source_unchanged'] and len(result['results'])==4
rows=[];agreement=collections.Counter()
for source in json.loads((B/'inputs.json').read_text())['rows']:
 c=prepare(source);r=next(r for r in result['results'] if r['task']==source['task']);cs=c['candidates'];old=c['validations'];new=ep.validated_validation_response(json.dumps(r['validations']),candidates=cs,artifact_ids=c['artifact_ids'])
 oldacc,olddec=ep.admit_candidates(cs,old,c['pairs'],c['current']);newacc,newdec=ep.admit_candidates(cs,new,c['pairs'],c['current']);changes=[]
 for a,b in zip(old,new,strict=True):
  av={x.artifact_id:x for x in a.artifact_applications};bv={x.artifact_id:x for x in b.artifact_applications};assert set(av)==set(bv)
  for aid,x in av.items():
   y=bv[aid];same=x.level==y.level;agreement['same' if same else 'changed']+=1
   if not same:changes.append(dict(criterion_id=a.criterion_id,artifact_id=aid,original_level=x.level,repeated_level=y.level,original_reason=x.reason,repeated_reason=y.reason))
 idx=next(i for i,x in enumerate(cs) if x.criterion.criterion_id==source['original_candidate_id']);cand=cs[idx];apps={x.artifact_id:x.level for x in old[idx].artifact_applications};order={lev:i for i,(lev,_,_) in enumerate(cand.criterion.levels)};pairs={p.pair_id:p for p in c['pairs']}
 keep=tuple(pid for pid in cand.criterion.provenance_pair_ids if order[apps[pairs[pid].preferred_artifact_id]]<order[apps[pairs[pid].rejected_artifact_id]])
 modified=list(cs);modified[idx]=replace(cand,criterion=replace(cand.criterion,provenance_pair_ids=keep))
 _,od=ep.admit_candidates(tuple(modified),old,c['pairs'],c['current']);_,nd=ep.admit_candidates(tuple(modified),new,c['pairs'],c['current']);assert od[idx].accepted
 rows.append(dict(task=source['task'],replicate=source['replicate'],candidate_id=cand.criterion.criterion_id,original_admitted=len(oldacc),repeat_admitted=len(newacc),original_fixed_repair_decision=od[idx].reason,repeated_fixed_repair_decision=nd[idx].reason,fixed_citations=keep,application_changes=changes))
out=ROOT/'docs/reports/2026-09-09';payload=dict(source_job='10370858',report_job=os.environ['SLURM_JOB_ID'],application_agreement=dict(agreement),rows=rows,source_result_sha256=hashlib.sha256((BASE/'result.json').read_bytes()).hexdigest())
with (out/'cue-validation-repeat-result.json').open('x') as f:json.dump(payload,f,indent=2);f.write('\n')
lines=['# Exact saved-candidate validation repeat','','Same candidate text/levels and public artifact inputs; no induction, revisions or outcome audits. Original source judgments remain unchanged.','','| Context | Original admitted | Repeated admitted | Original fixed citation repair | Same repair, repeated judgments | Changed applications |','|---|---:|---:|---|---|---:|']
for r in rows:lines.append(f"| {r['task']}/{r['replicate']} | {r['original_admitted']} | {r['repeat_admitted']} | {r['original_fixed_repair_decision']} | {r['repeated_fixed_repair_decision']} | {len(r['application_changes'])} |")
lines += ['',f'Exact level agreement: {agreement["same"]}/{sum(agreement.values())}; changed: {agreement["changed"]}. This is one repeat on an enriched four-context diagnostic set, not an estimate of panel or full Result20 reliability.','','Fixed citation repair uses the originally selected supporting citations; it is not reselected to fit new judgments. No production admission rule was changed. The comparison tests whether the original replay finding survives independent application of identical criteria.','','Inspect the source-linked changed reasons in the adjacent JSON before choosing the next policy mechanism. Repeated-model disagreement is not human ground truth and does not justify threshold tuning or selecting whichever judgment admits a desired criterion.','']
with (out/'cue-validation-repeat-result.md').open('x') as f:f.write('\n'.join(lines))
print('\n'.join(lines[:12]))
