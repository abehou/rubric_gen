"""Assemble read-only RH-positive inspection packets; never creates verdicts."""
import os,json
from pathlib import Path
from collections import defaultdict
from report_sources import RUN,OUT,PUBLIC,PANEL,read,sha,write
from report_pipeline import table


def events(path,turn):
 result=[]
 for lineno,line in enumerate(path.open(),1):
  try:event=json.loads(line)
  except ValueError:continue
  item=event.get('item')
  if event.get('type')!='item.completed' or not isinstance(item,dict):continue
  result.append({**{k:v for k,v in item.items() if k not in ('type','id','source')},
    'native_source':item.get('source'),'turn':turn,'source':str(path),'source_line':lineno,'kind':item['type']})
 return result

def main():
 assert os.environ.get('SLURM_JOB_ID')
 studies=list((RUN/'study').glob('*/study.json'));assert len(studies)==1
 ledger=read(studies[0]);study=studies[0].parent
 assignments=[r for r in ledger['records'] if r['condition_id'].endswith('red-team-trace')]
 assert len(assignments)==120 and all(r['status']=='completed' for r in assignments)
 by_path={str(study/r['experiment_dir']):r for r in assignments}
 summaries=list((RUN/'audit'/ledger['experiment_id']/'direct_full_trajectory/evaluations').glob('*/summary.json'));assert len(summaries)==1
 panel=read(summaries[0]);records=panel['records']
 assert len(records)==len(assignments)*len(PANEL)
 assert {(r['source_path'],r['model']) for r in records}=={(p,m) for p in by_path for m in PANEL}
 assert all(r['status']=='completed' and r['verdict'] is not None for r in records)
 rows=[]
 for r in records:
  assignment=by_path[r['source_path']]
  rows.append({**assignment,'state_path':str(Path(r['source_path'])/'state.json'),'model':r['model'],'direct':{'full_trajectory':r['verdict']}})
 write(PUBLIC/'full-trajectory-panel-inspection-receipt.json',{'summary_path':str(summaries[0]),'summary_sha256':sha(summaries[0]),'completed_cells':len(records),'models':list(PANEL),'purpose':'Read-only case inspection after the complete full-trajectory panel; other outcome stages may still be running.','provider_calls':0})
 cases=defaultdict(list)
 for row in rows:cases[row['assignment_id']].append(row)
 index=[]
 for aid,rs in sorted(cases.items()):
  if not any(r['direct']['full_trajectory']['decision']=='reward_hacking_detected' for r in rs):continue
  root=Path(rs[0]['state_path']).parent;state=read(root/'state.json');public_events=[];sources={}
  initial=root/'submissions/s000/trajectory.stream.jsonl'
  if initial.exists():public_events+=events(initial,0);sources[str(initial)]=sha(initial)
  for p in sorted((root/'turns').glob('turn-*/trajectory.stream.jsonl')):
   public_events+=events(p,int(p.parent.name.split('-')[-1]));sources[str(p)]=sha(p)
  prompts=[]
  for p in sorted((root/'turns').glob('turn-*/prompt.txt')):
   prompts.append({'turn':int(p.parent.name.split('-')[-1]),'text':p.read_text(),'path':str(p),'sha256':sha(p)})
  rules=[]
  for p in sorted((root/'rubric-generations').glob('generation-*/criteria.json')):
   g=int(p.parent.name.split('-')[-1])
   for c in read(p):
    if c['source_generation']==g:rules.append({'admission_generation':g,**c,'source':str(p),
      'first_verbatim_requirement_in_prompt':min((x['turn'] for x in prompts if c['requirement'] in x['text']),default=None)})
  reminders=[read(p) for p in sorted((root/'trace-defense-reminders').glob('s*.json'))]
  bindings=[read(p) for p in sorted((root/'submission-rubric-bindings').glob('s*.json'))]
  packet={'assignment_id':aid,'task_id':rs[0]['task_id'],'replicate':rs[0]['replicate'],'root':str(root),'state':state,
   'auditors':{r['model']:r['direct']['full_trajectory'] for r in rs},'events':public_events,'prompts':prompts,'rules':rules,'reminders':reminders,'bindings':bindings,
   'sources':sources,'first_event_policy':'Human read-only interpretation required; these packets do not rescore the official verdict.'}
  path=OUT/'positive-inspection'/f'{aid}.json';write(path,packet)
  index.append({'assignment_id':aid,'arm':'user' if rs[0]['condition_id'].startswith('user') else 'full','task_id':rs[0]['task_id'],'replicate':rs[0]['replicate'],
    'positive_auditors':[r['model'] for r in rs if r['direct']['full_trajectory']['decision']=='reward_hacking_detected'],
    'official_verdicts':packet['auditors'],'first_online_admission_generation':min((c['admission_generation'] for c in rules if c['admission_generation']>=2),default=None),
    'first_focused_reminder_turn':min((r['solver_turn'] for r in reminders if r['selection']),default=None),
    'first_defense_possible_turn':1,'packet_path':str(path),'packet_sha256':sha(path),'packet_bytes':path.stat().st_size})
 table('RH-positive-case-index.csv',index)
 write(PUBLIC/'RH-positive-case-index.json',index)
 print(json.dumps({'positive_assignments':len(index),'by_arm':{a:sum(r['arm']==a for r in index) for a in ('full','user')},'new_verdicts':0}),flush=True)

if __name__=='__main__':main()
