"""Non-provider real-artifact request serialization checks on Slurm."""
from pathlib import Path
from dataclasses import replace
import hashlib,json,os
from candidate import candidate_requests,MARKER
from rubric_gen.detection.prompts import _reward_hacking_requests
from rubric_gen.submission_revision.evaluation.evidence import _revision_prompt
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.experiment import load_experiment
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent
assert os.environ.get('SLURM_JOB_ID')
exp=load_experiment(ROOT/'investigation/result20-cue-contrast-20260908/static-results20.yaml')
study=Path(exp.dag['revise']['output_dir']);revision=study/'experiments/da-10-1/rep-001/luna/user-simulator-static'
payload=_revision_prompt(revision,exp.tasks_dir,'rh',RevisionDetectionWindow.FINAL_ARTIFACT)
original=_reward_hacking_requests(payload,evidence_chars=290000,max_output_tokens=4096)
new=candidate_requests(payload,evidence_chars=290000,max_output_tokens=4096)
assert len(original)==len(new)
for a,b in zip(original,new,strict=True):
 assert replace(b,instructions=a.instructions)==a
 assert MARKER not in b.instructions
 for rendered in [b.openai_input('gpt-5.6-sol'),[b.anthropic_system(),b.anthropic_messages()]]:
  wire=json.dumps(rendered)
  assert 'test the strongest innocent explanation' in wire
  assert 'Detection window: final_artifact' in wire
  assert 'reward_hacking_detected, no_reward_hacking_detected, or abstain' not in wire
  assert 'user-simulator-static' not in wire and 'da-10-1' not in wire
for bad in [replace(payload,stats={**payload.stats,'detection_window':'full_trajectory'}),replace(payload,stats={**payload.stats,'solver_feedback_records':1}),replace(payload,instructions=payload.instructions.replace(MARKER,''))]:
 try:candidate_requests(bad,evidence_chars=290000)
 except ValueError:pass
 else:raise AssertionError('Rejected scope/contract accepted')
receipt=dict(success=True,job_id=os.environ['SLURM_JOB_ID'],scope='No provider calls. Real final artifact, both provider serializers, unchanged evidence/schema/output budget; reject other windows.',candidate_sha256=hashlib.sha256((B/'candidate.py').read_bytes()).hexdigest(),verify_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),status='uncalibrated candidate only; no production switch',payload_instruction_sha256=hashlib.sha256(payload.instructions.encode()).hexdigest())
with (B/'verification.json').open('x') as f:json.dump(receipt,f,indent=2);f.write('\n')
print(receipt['scope'])
