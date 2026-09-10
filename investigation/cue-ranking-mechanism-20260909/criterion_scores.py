"""Map stable elicited IDs to numbered frozen judgment criteria."""
import json,re,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2];p=root/'docs/reports/2026-09-09/cue-ranking-enabled-delivery.json';d=json.loads(p.read_text());out=[]
for row in d['rows']:
 b=Path(row['generation_path']).parent.parent;checks=[]
 for c in row['checkpoints']:
  g=b/'rubric-generations'/f"generation-{c['generation']:04d}"
  rubric=(g/'rubric.txt').read_text();parts=re.split(r'(?m)^Criterion (\d+):',rubric)
  matches=[parts[i] for i in range(1,len(parts),2) if f"Elicited criterion ID: {row['criterion_id']}" in parts[i+1]]
  assert len(matches)==1,(g,matches)
  r=json.loads((b/'rubric-evaluations'/f"{c['submission']}.json").read_text())
  vpath=b/'judgments'/c['submission']/r['rubric_sha256']/'score_validation.json';v=json.loads(vpath.read_text());assert hashlib.sha256(vpath.read_bytes()).hexdigest()==r['score_validation_sha256']
  k='criterion_'+matches[0];checks.append({**c,'criterion_key':k,'criterion_score':v['criterion_scores'][k],'criterion_level':v['criterion_levels'][k]})
 out.append({**row,'checkpoints':checks})
p=root/'docs/reports/2026-09-09/cue-ranking-criterion-assessments.json';p.write_text(json.dumps({'rows':out},indent=2)+'\n')
lines=['# Criterion-specific assessment of rule-enabled admissions','','Stable elicited IDs mapped through exact rendered rubric markers; judgment hashes checked against each native evaluation receipt. Scores below are the frozen weak judge assessments, not human truth.','','| Assignment | Generation | Violated checkpoints / assessed | Violations with subsequent feedback |','|---|---:|---:|---:|']
for r in out:
 cs=r['checkpoints'];bad=[c for c in cs if c['criterion_score']<0];lines.append(f"| {r['assignment']} | {r['generation']} | {len(bad)}/{len(cs)} | {sum(c['feedback'] is not None for c in bad)} |")
lines+=['','Every feedback payload and exact per-criterion score is preserved in the adjacent JSON. Absence of a feedback request when the criterion scores zero does not demonstrate a dropped violation. Terminal admissions cannot change subsequent behavior.']
p.with_suffix('.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines))
