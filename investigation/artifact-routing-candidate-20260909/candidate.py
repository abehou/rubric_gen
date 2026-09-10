"""Uncalibrated artifact-only routing candidate; never used by production."""
from dataclasses import replace
from rubric_gen.detection.prompts import _reward_hacking_requests
MARKER='\nReturn exactly one JSON object with keys decision, confidence, evidence_locations, findings, and analysis.'
def candidate_requests(payload,*,evidence_chars,max_output_tokens=4096):
 if payload.stats.get('detection_window')!='final_artifact' or payload.stats.get('solver_feedback_records')!=0:
  raise ValueError('Candidate is restricted to final artifacts without feedback')
 if payload.instructions.count(MARKER)!=1:
  raise ValueError('Unexpected forensic contract; refuse implicit adaptation')
 guidance=payload.instructions.split(MARKER)[0].rstrip()
 if 'Detection window: final_artifact' not in guidance:raise ValueError('Wrong forensic window')
 # Route the actual frozen forensic guidance, but do not introduce its conflicting
 # categorical output contract into the existing numerical monitor schema.
 original=_reward_hacking_requests(payload,evidence_chars=evidence_chars,max_output_tokens=max_output_tokens)
 return tuple(replace(r,instructions=guidance+'\n\nUse the original numerical score and reason output format below.\n\n'+r.instructions) for r in original)
