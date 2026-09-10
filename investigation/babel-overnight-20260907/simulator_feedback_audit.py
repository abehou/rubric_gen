"""Read-only feedback exposure audit of the corrected historical dev3 control."""
from collections import Counter
import json
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
rows=json.loads((HERE/'dev3-reconstruction.json').read_text())['rows']
assignments={r['assignment']:r for r in rows if r['arm']=='control' and r['condition']=='user-simulator-static'}
result=[]
for aid,row in assignments.items():
    exp=(ROOT/row['state_path']).parent
    state=json.loads((exp/'state.json').read_text())
    feedback=[]
    for p in sorted((exp/'feedback').glob('*.json')):
        value=json.loads(p.read_text())
        feedback.append(dict(checkpoint=p.stem,decision=value['decision'],n=len(value['concerns']),categories=[x['category'] for x in value['concerns']],path=str(p.relative_to(ROOT))))
    panel=[r for r in rows if r['assignment']==aid and r['arm']=='control']
    result.append(dict(assignment=aid,task=row['task'],replicate=row['replicate'],feedback=feedback,
        monitor={r['model']:r['verdict']['score'] for r in panel},A={r['model']:r['A'] for r in panel},
        W=row['W'],retained_revisions=len(state['submission_ids'])-1,stop_reason=state['stop_reason']))
flat=[f for r in result for f in r['feedback']]
summary=dict(assignments=len(result),feedback_turns=len(flat),concern_count_distribution=dict(sorted(Counter(f['n'] for f in flat).items())),
    decisions=dict(Counter(f['decision'] for f in flat)),categories=dict(Counter(c for f in flat for c in f['categories'])),
    turns_affected_by_cap1=sum(f['n']>1 for f in flat),assignment_exposure=result)
(HERE/'simulator-feedback-audit.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='assignment_exposure'},indent=2))
