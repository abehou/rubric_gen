"""Fixed-checkpoint counterfactual selector replay, never a trajectory replay."""
import csv,json,subprocess
from pathlib import Path
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.trace_defense_delivery import select_reminder,numeric_literals
from rubric_gen.submission_revision.user_delivery_v3 import select_private_delivery
ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'docs/reports/2026-09-11/trace-attack-defense-v3'
OUT=ROOT/'docs/reports/2026-09-12/trace-user-parallel-diagnostics'
rows=[]; labels=[]
for variant,filename in [('v3','stress-user-forensics.json'),('v3.1','stress-v31-user-forensics.json'),('v3.2','stress-v32-user-forensics.json')]:
 for case in json.loads((OLD/filename).read_text())['cases']:
  root=Path(case['v3']['case']['root']);manifest=json.loads((root/'manifest.json').read_text());instruction=(Path(manifest['task_dir'])/'instruction.md').read_text()
  for saved in sorted((root/'trace-defense-reminders').glob('s*.json')):
   sid=saved.stem;record=json.loads(saved.read_text());binding=json.loads((root/'submission-rubric-bindings'/saved.name).read_text());gen=load_rubric_generation(root,binding['active_generation_round'])
   score=root/'judgments'/sid/gen.rubric.content_sha256/'score_validation.json'
   args=dict(generation=gen,score_validation_path=score,root=root,submission_id=sid,instruction=instruction)
   historical,oldskip=select_private_delivery(**args);correct,newskip=select_reminder(**args)
   assert historical==record['selection'] and oldskip==record['skipped'],(variant,root,sid,'historical selector does not reproduce saved receipt')
   oldcore=None if historical is None else {k:v for k,v in historical.items() if k!='focused_dynamic_check'}
   rows.append(dict(variant=variant,task=case['task_id'],replicate=case['replicate'],submission_id=sid,root=str(root),receipt=str(saved),generation=gen.generation_round,
       saved_choice=oldcore,correct_choice=correct,saved_skips=oldskip,correct_skips=newskip,choice_changed=oldcore!=correct,eligibility_changed=oldskip!=newskip))
  for t in case['v3']['turns']:
   if t.get('raw_proactive_only_revise'):
    labels.append(dict(variant=variant,task=case['task_id'],replicate=case['replicate'],**t))
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'selector-replay.json').write_text(json.dumps({'provider_calls':0,'interpretation':'One-step selector replay with SAVED previous-selection history and unchanged scores. Does not simulate altered future trajectories.','rows':rows,'proactive_label_examples':labels},indent=2)+'\n')
with (OUT/'selector-replay.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows({k:json.dumps(v) if isinstance(v,(dict,list)) else v for k,v in r.items()} for r in rows)
print(json.dumps({v:{'checkpoints':sum(r['variant']==v for r in rows),'choice_changes':sum(r['variant']==v and r['choice_changed'] for r in rows),'eligibility_changes':sum(r['variant']==v and r['eligibility_changed'] for r in rows)} for v in ('v3','v3.1','v3.2')}))
