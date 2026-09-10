"""Read completed native analysis; preserve auditor decisions and abstentions."""
from pathlib import Path
import collections, hashlib, json
ROOT=Path('/home/aydanh/repos/rubric_gen')
SOURCE=ROOT/'runs/babel-result20-cue-score-first-trace-20260909/comparison-v1/analysis.json'
def main(source=SOURCE, stem="score-first-case-transitions", title="Completed score-first Result20"):
 data=json.loads(source.read_text());rows=data['rows'];assert len(rows)==240
 groups=collections.defaultdict(dict)
 for row in rows:
  key=(row['task_id'],row['replicate'],row['model']);arm=row['analysis_condition'].split('/')[0]
  assert arm not in groups[key];groups[key][arm]=row
 assert len(groups)==120 and all(set(v)=={'static','trace'} for v in groups.values())
 for arms in groups.values():
  assert arms['static']['initial_submission_sha256']==arms['trace']['initial_submission_sha256']
  assert arms['static']['selected_rubric_sha256']==arms['trace']['selected_rubric_sha256']
 summaries=collections.defaultdict(collections.Counter);cases=[]
 for (task,rep,model),arms in sorted(groups.items()):
  for window in ('full_trajectory','post_update','final_artifact','final_revision'):
   ds=[arms[a]['direct'][window] for a in ('static','trace')]
   decisions=[d['decision'] for d in ds]
   positive='reward_hacking_detected';negative='no_reward_hacking_detected'
   if any(x not in (positive,negative) for x in decisions):category='includes abstention'
   elif decisions==[positive,positive]:category='persists'
   elif decisions==[positive,negative]:category='disappears'
   elif decisions==[negative,positive]:category='new under trace'
   else:category='neither'
   summaries[(model,window)][category]+=1
   if category!='neither':
    cases.append(dict(task=task,replicate=rep,model=model,window=window,category=category,
      static=ds[0],trace=ds[1],states={a:arms[a]['state_path'] for a in arms},
      state_hashes={a:arms[a]['state_sha256'] for a in arms},
      values={a:arms[a]['values'] for a in arms}))
 out=ROOT/'docs/reports/2026-09-09';out.mkdir(exist_ok=True)
 payload=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),cases=cases,
  summaries=[dict(model=m,window=w,counts=dict(c)) for (m,w),c in sorted(summaries.items())])
 (out/f'{stem}.json').write_text(json.dumps(payload,indent=2)+'\n')
 lines=[f'# {title}: matched case transitions','','Descriptive auditor decisions on 60 paired assignments. These are not human-verified causal classifications. Abstentions remain separate; cases can disagree across auditors. No new calls or changed scoring.','','| Auditor | Window | Persists | Disappears | New under trace | Neither | Includes abstention |','|---|---|---:|---:|---:|---:|---:|']
 for (m,w),counts in sorted(summaries.items()):
  assert sum(counts.values())==60
  lines.append('| '+m+' | '+w+' | '+' | '.join(str(counts[k]) for k in ('persists','disappears','new under trace','neither','includes abstention'))+' |')
 lines+=['','## Case review index','',f'Review full-trajectory and final-artifact transitions first. Source-linked reasons, saved state paths/hashes and quality/gap values are in [JSON]({stem}.json). Admission/delivery/violation/action still require direct evidence review; this index alone does not establish mechanism.','','| Task | Replicate | Auditor | Window | Transition | Static score | Trace score |','|---|---:|---|---|---|---:|---:|']
 for c in cases:
  if c['window'] in ('full_trajectory','final_artifact'):
   lines.append(f"| {c['task']} | {c['replicate']} | {c['model']} | {c['window']} | {c['category']} | {c['static']['score']} | {c['trace']['score']} |")
 lines+=['',f'Source: `{source.relative_to(ROOT)}`; SHA256 `{payload["source_sha256"]}`.','']
 (out/f'{stem}.md').write_text('\n'.join(lines))
 print('\n'.join(lines[:14]))
if __name__=='__main__':main()
