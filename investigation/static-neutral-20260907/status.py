"""Read-only bounded-run status; no provider access."""
import json
from pathlib import Path
from collections import Counter
from datetime import datetime
HERE=Path(__file__).resolve().parent
print(datetime.now().astimezone().isoformat())
for row in json.loads((HERE/'manifest.json').read_text())['configs']:
    study=Path(row['study']);audit=Path(row['audit']);p=study/'study.json'
    if not p.exists():continue
    data=json.loads(p.read_text())
    print(row['tag'],data['status'],dict(Counter(r['status'] for r in data['records'])))
    scores={}
    for stage in ['direct_full_trajectory','direct_post_update','direct_final_artifact','direct_final_revision']:
        d=Counter()
        for p in (audit/stage).glob('evaluations/*/cases/*/*/score.json'):
            d[json.loads(p.read_text())['model']]+=1
        if d:scores[stage]=dict(d)
    for stage in ['rubric_score','absolute_score','pairwise_preference']:
        n=len(list((audit/stage/'records').glob('*.json')))
        if n:scores[stage]=n
    if scores:print('  audits',scores)
