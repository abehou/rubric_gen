import json,hashlib
from pathlib import Path
from rubric_gen.submission_revision.feedback import active_violation_requirements
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
b=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/trace/study')
n=0;notes=0
for p in b.glob('*/experiments/*/*/*/*/turns/turn-*/prompt.txt'):
 base=p.parent.parent.parent; i=int(p.parent.name.split('-')[1])-1
 ep=base/'rubric-evaluations'/f's{i:03d}.json'
 if not ep.exists():continue
 e=json.loads(ep.read_text());g=load_rubric_generation(base,e['generation_round']);v=base/'judgments'/f's{i:03d}'/e['rubric_sha256']/'score_validation.json'
 assert hashlib.sha256(v.read_bytes()).hexdigest()==e['score_validation_sha256']
 req=active_violation_requirements(g,v);marker='\n\nActive rubric requirements needing attention:\n';text=p.read_text()
 if req:assert text.endswith(marker+'\n'.join('- '+r for r in req)),str(p);notes+=1
 else:assert marker not in text,str(p)
 n+=1
print(json.dumps({'checked_prompts':n,'verified_notes':notes,'mismatches':0}))
