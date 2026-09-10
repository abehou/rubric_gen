"""Describe native recovery exposure without excluding or rescoring assignments."""
import collections,hashlib,json,os,socket,time
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen')
REPORT=ROOT/'runs/babel-result20-current-20260908/report-v1'
EVENTS={'solver_session_discarded','turn_reset_after_interruption','turn_recovered','live_workspace_rebuilt','solver_model_recovered_from_completed_turn'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 source=REPORT/'analysis.json';data=json.loads(source.read_text());grouped=collections.defaultdict(list)
 for row in data['rows']:grouped[row['assignment_id']].append(row)
 if len(grouped)!=240 or any(len(v)!=2 or {r['model'] for r in v}!={'gpt-5.6-sol','claude-opus-5'} for v in grouped.values()):raise RuntimeError('requires complete240-assignment Sol/Opus comparison')
 rows=[];inputs={str(source):sha(source)}
 for aid,panel in sorted(grouped.items()):
  state_paths={r['state_path'] for r in panel}
  if len(state_paths)!=1:raise RuntimeError('panel state paths disagree')
  state_path=Path(next(iter(state_paths)));state=json.loads(state_path.read_text())
  if state['phase']!='completed':raise RuntimeError('revision no longer complete')
  events_path=state_path.parent/'events.jsonl';events=[json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
  counts=collections.Counter(e.get('event') for e in events if e.get('event') in EVENTS)
  resets=[{'event':e['event'],'turn':e.get('turn'),'reason':e.get('reason')} for e in events if e.get('event') in EVENTS]
  archive=state_path.parent/'interrupted-turns'
  archived=len(list(archive.glob('turn-*'))) if archive.is_dir() else 0
  rows.append(dict(assignment_id=aid,condition=panel[0]['condition_id'],task=panel[0]['task_id'],replicate=panel[0]['replicate'],events=dict(counts),details=resets,archived_turns=archived,session_reset=counts['solver_session_discarded']>0))
  inputs[str(events_path)]=sha(events_path);inputs[str(state_path)]=sha(state_path)
 summaries={}
 for condition in sorted({r['condition'] for r in rows}):
  selected=[r for r in rows if r['condition']==condition]
  summaries[condition]={'assignments':len(selected),'with_session_reset':sum(r['session_reset'] for r in selected),'with_archived_turns':sum(r['archived_turns']>0 for r in selected),'event_totals':{event:sum(r['events'].get(event,0) for r in selected) for event in sorted(EVENTS)}}
 if any(sha(Path(n))!=v for n,v in inputs.items()):raise RuntimeError('source changed during read-only recovery summary')
 output=REPORT/'recovery-provenance';output.mkdir(exist_ok=False)
 result=dict(job_id=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),script_sha256=sha(Path(__file__)),input_sha256s=inputs,conditions=summaries,rows=rows,interpretation='Descriptive recovery exposure only. All240 assignments remain in the primary analysis. A native-valid restart does not prove identical session context; inspect imbalances before claiming a robust policy effect, and use a clean frozen confirmation if needed. No endpoint,threshold,model,or artifact changed.')
 (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps(summaries,indent=2))
if __name__=='__main__':main()
