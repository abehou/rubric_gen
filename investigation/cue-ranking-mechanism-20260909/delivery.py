"""Inventory actual post-admission feedback; never infer delivery from admission."""
import json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=root/'docs/reports/2026-09-09/cue-ranking-rule-exposure.json';x=json.loads(p.read_text());rows=[]
for e in x['enabled_admissions']:
 g=Path(e['generation_path']);b=g.parent.parent
 criterion=next(c for c in json.loads((g/'criteria.json').read_text()) if c['criterion_id']==e['criterion_id'])
 checkpoints=[]
 for f in sorted((b/'rubric-evaluations').glob('s*.json')):
  r=json.loads(f.read_text())
  if r['generation_round']<e['generation']:continue
  fp=b/'feedback-generations'/f.name
  feedback=json.loads(fp.read_text()) if fp.exists() else None
  checkpoints.append({'submission':f.stem,'generation':r['generation_round'],'total_elicited_penalty':r['elicited_penalty'],'selected_score':r['reference_score'],'feedback':feedback['output'] if feedback else None,'feedback_sha256':hashlib.sha256(fp.read_bytes()).hexdigest() if fp.exists() else None,'evaluation_sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
 rows.append({**e,'criterion':criterion,'checkpoints':checkpoints})
p=root/'docs/reports/2026-09-09/cue-ranking-enabled-delivery.json';p.write_text(json.dumps({'rows':rows,'limitation':'Total elicited penalty can reflect other criteria; feedback semantic delivery requires reading the saved text, not keyword or admission counts.'},indent=2)+'\n')
lines=['# Delivery after rule-enabled admissions','','Complete census of the seven admissions, including terminal admissions without another solver turn. Frozen outputs only.','','| Assignment | Admission generation | Feedback checkpoints after admission | Checkpoints with any elicited penalty |','|---|---:|---:|---:|']
for r in rows:lines.append(f"| {r['assignment']} | {r['generation']} | {sum(c['feedback'] is not None for c in r['checkpoints'])} | {sum(c['total_elicited_penalty']<0 for c in r['checkpoints'])} |")
lines+=['','Two admissions occur at generation10, after the revision budget is exhausted, and have no subsequent simulator feedback. They cannot change the already-completed natural trajectory. For the other admissions, the adjacent JSON preserves every subsequent feedback payload and composed penalty. Total penalty is not criterion-specific.','','At the first feedback after admission: da13-1rep1 requests a missing CSV rather than the admitted field/transformation consistency issue; da14-8rep2g3 addresses numerical reconstruction and cutoff reporting rather than the admitted inferential test; da14-3rep3 receives accept with no concerns; da10-1rep1g6 receives other missing-output/method concerns rather than multiplicity correction. da12-2rep3g5 does request executable evidence for reported outputs, which aligns with its admitted evidence-support criterion. These observations concern first feedback only, and absence of a request is not a defect if the criterion was satisfied. Criterion-specific assessment must establish an actual violation before diagnosing dropped feedback.']
p.with_suffix('.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines[:13]))
