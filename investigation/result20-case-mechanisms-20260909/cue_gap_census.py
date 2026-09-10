"""Descriptive paired decomposition of frozen rubric-cue results; no API calls."""
from pathlib import Path
import collections,hashlib,json,statistics
ROOT=Path('/home/aydanh/repos/rubric_gen')
def main():
 source=ROOT/'runs/babel-result20-cue-contrast-20260908/comparison-v1/analysis.json';data=json.loads(source.read_text())
 paired=collections.defaultdict(dict)
 for r in data['rows']:
  k=(r['task_id'],r['replicate'],r['model']);arm=r['analysis_condition'].split('/')[0]
  assert arm not in paired[k];paired[k][arm]=r
 assert len(paired)==120
 tasks=collections.defaultdict(list);cases=[]
 keys=['W','W_train','S','H','A','WS','SH','HA','WA','elicited_penalty']
 for (task,rep,model),arms in sorted(paired.items()):
  assert set(arms)=={'static','trace'}
  assert arms['static']['initial_submission_sha256']==arms['trace']['initial_submission_sha256']
  assert arms['static']['selected_rubric_sha256']==arms['trace']['selected_rubric_sha256']
  delta={k:arms['trace']['values'][k]-arms['static']['values'][k] for k in keys}
  assert abs(delta['WS']-(delta['W']-delta['S']))<1e-8
  assert abs(delta['WA']-(delta['W']-delta['A']))<1e-8
  tasks[task].append(delta)
  cases.append(dict(task=task,replicate=rep,model=model,delta=delta,
   direct={a:arms[a]['direct'] for a in arms},states={a:arms[a]['state_path'] for a in arms}))
 assert len(tasks)==20 and all(len(v)==6 for v in tasks.values())
 summary=[dict(task=t,delta={k:statistics.mean(r[k] for r in rs) for k in keys}) for t,rs in sorted(tasks.items())]
 aggregate={k:statistics.mean(r['delta'][k] for r in summary) for k in keys}
 out=ROOT/'docs/reports/2026-09-09';payload=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),aggregate=aggregate,tasks=summary,cases=cases)
 (out/'rubric-cue-gap-census.json').write_text(json.dumps(payload,indent=2)+'\n')
 lines=['# Rubric-cue paired gap census','','All20tasks ×3replicates ×2auditors; trace minus static. Arithmetic decomposition, not causal attribution. No case exclusions or new provider calls.','','Aggregate differences: '+', '.join(f'{k}={v:+.3f}' for k,v in aggregate.items())+'.','','| Task | ΔW | ΔS | ΔH | ΔA | ΔW-S | ΔS-H | ΔH-A | ΔW-A |','|---|'+'---:|'*8]
 for r in sorted(summary,key=lambda x:x['delta']['WS'],reverse=True):
  lines.append('| '+r['task']+' | '+' | '.join(f"{r['delta'][k]:+.2f}" for k in ['W','S','H','A','WS','SH','HA','WA'])+' |')
 lines+=['','Task sorting identifies review priorities only; all tasks remain in outcomes. Inspect both worse-gap and improved-gap cases and their auditor-specific RH reasons before proposing a policy. W_train remains separate; penalty-induced score changes are not quality gains.','','Full case deltas, frozen audit reasons and state paths: [JSON](rubric-cue-gap-census.json).',f'Source SHA256: `{payload["source_sha256"]}`.','']
 (out/'rubric-cue-gap-census.md').write_text('\n'.join(lines));print('\n'.join(lines[:13]))
if __name__=='__main__':main()
