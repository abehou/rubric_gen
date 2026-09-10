import json
from context import ep
from rubric_gen.submission_revision.evolution_serialization import canonical_json

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
