"""Verify completed candidate note delivery against frozen native judgments."""
import hashlib,json,os
from pathlib import Path
from rubric_gen.submission_revision.feedback import active_violation_requirements
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
BASE=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
assert os.environ.get('SLURM_JOB_ID')
RECOVERY=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-pair-recovery-20260909')
receipt=next((RECOVERY/'owners/trace-results20').glob('10374492-*/launch.json'))
assert json.loads(receipt.with_name('result.json').read_text())['success']
replacement=json.loads(receipt.read_text());original=json.loads(next((BASE/'owners/trace-results20').glob('10373129-*/launch.json')).read_text())
original_states=list(Path(original['outputs']['revise']['output_dir']).glob('experiments/*/*/*/*/state.json'))
failed=[p for p in original_states if json.loads(p.read_text())['phase']!='completed']
assert len(failed)==1
assert json.loads((failed[0].parent/'manifest.json').read_text())['assignment_id']=='da-14-3--rep-001--solver-luna--user-simulator-red-team-trace'
states=[p for p in original_states if p not in failed]+list(Path(replacement['outputs']['revise']['output_dir']).glob('experiments/*/*/*/*/state.json'))
assert len(states)==60 and all(json.loads(p.read_text())['phase']=='completed' for p in states)
assert len({json.loads((p.parent/'manifest.json').read_text())['assignment_id'] for p in states})==60
rows=[]
for state in states:
 b=state.parent;manifest=json.loads((b/'manifest.json').read_text());assert manifest['deliver_active_violations'] is True
 for prompt in sorted((b/'turns').glob('turn-*/prompt.txt')):
  checkpoint=int(prompt.parent.name.split('-')[1])-1
  evpath=b/'rubric-evaluations'/f's{checkpoint:03d}.json';e=json.loads(evpath.read_text())
  generation=load_rubric_generation(b,e['generation_round'])
  score=b/'judgments'/f's{checkpoint:03d}'/e['rubric_sha256']/'score_validation.json'
  assert hashlib.sha256(score.read_bytes()).hexdigest()==e['score_validation_sha256']
  requirements=active_violation_requirements(generation,score)
  text=prompt.read_text();marker='\n\nActive rubric requirements needing attention:\n'
  if requirements:
   expected=marker+'\n'.join('- '+r for r in requirements)
   assert text.endswith(expected),(prompt,'note differs')
  else:assert marker not in text,(prompt,'unearned note')
  rows.append(dict(assignment_id=manifest['assignment_id'],checkpoint=checkpoint,prompt=str(prompt),prompt_sha256=hashlib.sha256(prompt.read_bytes()).hexdigest(),requirements=list(requirements)))
summary=dict(assignments=60,submitted_prompts=len(rows),notes=sum(bool(r['requirements']) for r in rows),assignments_with_notes=len({r['assignment_id'] for r in rows if r['requirements']}))
out=BASE/'delivery-recovered-v1';out.mkdir(exist_ok=False)
(out/'analysis.json').write_text(json.dumps(dict(summary=summary,rows=rows,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),indent=2)+'\n')
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-active-delivery.md').write_text('# Completed active-violation delivery audit\n\n'+json.dumps(summary,indent=2)+'\n\nEvery saved submitted prompt checked against its native criterion judgment. Counts establish delivery, not solver compliance or causal mitigation. Full evidence: '+str(out/'analysis.json')+'\n')
print(summary)
