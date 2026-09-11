import json
from pathlib import Path
r=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/phase-a/dev1-001/requests')
for p in sorted(r.glob('*/result.json')):
 d=json.loads(p.read_text())
 if d['accounting']['contract_invalid_attempts']:
  print('REQUEST',p.parent.name,d['request']['stage'])
  for a in sorted(p.parent.glob('attempt-*.json')):
   x=json.loads(a.read_text())
   print('attempt',x['attempt'],x['status'],x.get('validation_errors'), 'parsed',x.get('parsed_response'))
