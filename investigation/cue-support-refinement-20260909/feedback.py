"""Expose only prior applications to already shown induction artifacts."""
import json,re
from context import ep
from rubric_gen.submission_revision.evolution_serialization import canonical_json

def add_feedback(ctx):
 original=json.loads(ctx['request']['evidence']);visible={a['artifact_id'] for a in original['artifacts']};induction={p.pair_id:p for p in ctx['induction']}
 accepted,decisions=ep.admit_candidates(ctx['candidates'],ctx['validations'],ctx['pairs'],ctx['current']);assert not accepted,'refinement trigger requires zero original admissions'
 feedback=[]
 for candidate,validation,decision in zip(ctx['candidates'],ctx['validations'],decisions,strict=True):
  if decision.reason!='criterion_support_failed':continue
  apps={a.artifact_id:a for a in validation.artifact_applications};pairs=[]
  for pid in candidate.criterion.provenance_pair_ids:
   assert pid in induction
   p=induction[pid];assert {p.preferred_artifact_id,p.rejected_artifact_id}<=visible
   pair={'pair_id':pid}
   for role,aid in [('preferred',p.preferred_artifact_id),('rejected',p.rejected_artifact_id)]:
    a=apps[aid];assert set(re.findall(r'artifact_[0-9a-f]{16}',a.reason))<=visible
    assert set(re.findall(r'pair_[0-9a-f]{16}',a.reason))<=set(induction)
    pair[role]={'artifact_id':aid,'level':a.level,'reason':a.reason}
   pairs.append(pair)
  feedback.append({'previous_candidate':candidate.as_dict(),'cited_induction_applications':pairs})
 assert feedback
 new={**original,'prior_induction_feedback':feedback}
 assert {k:v for k,v in new.items() if k!='prior_induction_feedback'}==original
 return canonical_json(new)

def verify_control(ctx):
 from pathlib import Path
 import dataclasses
 root=Path('/home/aydanh/repos/rubric_gen/runs/cue-citation-diagnostic-10370826')/f"{ctx['row']['task']}-{ctx['row']['replicate']}-control"
 saved=json.loads((root/'result.json').read_text());assert saved['accepted']==0
 inputs=[];source_files=[root/'result.json']
 for p in root.glob('calls/*/request.json'):
  r=json.loads(p.read_text());source_files.append(p);source_files.extend(sorted(p.parent.glob('output-*.json')))
  if r['stage']=='induction':inputs.append((p,r))
 assert len(inputs)==1
 p,r=inputs[0];assert r['evidence']==ctx['request']['evidence'] and r['schema']==ctx['request']['response_schema'] and r['instructions']==ep.induction_instructions() and r['contract']==ctx['row']['provider_contract']
 outputs=sorted(p.parent.glob('output-*.json'));assert len(outputs)==1
 raw=json.loads(outputs[0].read_text())['response_text'];cs=ep.validated_induction_response(raw,original_rubric=ctx['original'],current_generation=ctx['current'],generation_round=ctx['n'],level_labels=ep.required_level_labels(ctx['original']),induction_gaps=ctx['induction'])
 assert [c.as_dict() for c in cs]==saved['candidates']
 from context import ea
 vs=ep.validated_validation_response(canonical_json(saved['validations']),candidates=cs,artifact_ids=ea.validation_artifact_ids(ctx['pairs']))
 accepted,decisions=ep.admit_candidates(cs,vs,ctx['pairs'],ctx['current']);assert len(accepted)==saved['accepted']
 assert canonical_json([dataclasses.asdict(d) for d in decisions])==canonical_json(saved['decisions'])
 return source_files
