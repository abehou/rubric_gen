import json
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
B=Path(__file__).resolve().parent; E=load_experiment(B/'result20.yaml')
root=Path(str(E.dag['revise']['output_dir']))
print('root',root)
for p in sorted(root.glob('**/study.json')):
 try:
  o=json.loads(p.read_text()); print('study',p,'kind',o.get('kind'),'experiment_id',o.get('experiment_id'),'status',o.get('status'),'records',len(o.get('records',[])))
  print([(r.get('assignment_id'),r.get('status'),r.get('condition_id'),r.get('experiment_dir')) for r in o.get('records',[])][:10])
 except Exception as e: print('bad',p,type(e).__name__,str(e))
print('recovery',root.parent.parent/'recovery-v21.json')
q=root.parent.parent/'recovery-v21.json'
print(q.exists(), q.read_text()[:500] if q.exists() else '')
