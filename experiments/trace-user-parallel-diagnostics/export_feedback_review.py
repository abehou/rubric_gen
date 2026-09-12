"""Read-only local review copy of the fixed feedback diagnostic evidence."""
import json
from pathlib import Path
B=Path(__file__).resolve().parent
R=Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-parallel-diagnostics-20260912/feedback-checks')
rows=[json.loads(p.read_text()) for p in sorted((R/'inputs').glob('*.json'))]
(B/'feedback-review-inputs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'checkpoints':len(rows),'provider_calls':0}))
