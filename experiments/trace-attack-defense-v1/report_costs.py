"""Saved usage and capacity-journal accounting; never queries a provider."""
import os,json
from pathlib import Path
from types import SimpleNamespace
from collections import defaultdict,Counter
from statistics import mean
from report_sources import ROOT,RUN,OUT,PUBLIC,PANEL,read,sha,write
from report_pipeline import table
from rubric_gen.detection.costs import usage_tokens,request_cost
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.pricing import PRICING_AS_OF


def normalized(provider,usage):
 return usage_tokens(SimpleNamespace(provider=provider,provider_metadata={'usage':usage}))

def model_receipt(stage,model,provider,usage,path,response_id,**extra):
 tokens=normalized(provider,usage)
 return {'stage':stage,'model':model,'provider':provider,'response_id':response_id,'path':str(path),
  'usage_available':tokens is not None,**(tokens or {}),'usage_based_usd':request_cost(model,**tokens) if tokens else None,**extra}

def stream_receipts(paths,stage,model='gpt-5.6-luna'):
 threads={};events=Counter();streams=0
 for path in paths:
  streams+=1
  for line in path.open():
   try:event=json.loads(line)
   except ValueError:continue
   events[event.get('type','unknown')]+=1
   if event.get('type')!='turn.completed' or not isinstance(event.get('usage'),dict):continue
   key=event.get('thread_id',str(path));cost=RunCost.from_event(event,model=model)
   usage=event['usage'];item=threads.setdefault(key,{'stage':stage,'model':model,'thread_id':key,'path':str(path),'usage':{},'estimated_cost_usd':0})
   for name,value in usage.items():
    if isinstance(value,int):item['usage'][name]=max(item['usage'].get(name,0),value)
   if cost.estimated_cost_usd is not None:item['estimated_cost_usd']=max(item['estimated_cost_usd'],cost.estimated_cost_usd)
 return list(threads.values()),{'stage':stage,'streams':streams,'events':dict(events),'threads_with_usage':len(threads),
  'estimated_lower_bound_usd':sum(x['estimated_cost_usd'] for x in threads.values()),
  'usage_totals':dict(sum((Counter(x['usage']) for x in threads.values()),Counter())),
  'internal_model_request_count':'not exposed by saved agent protocol; agent turns and tool events reported separately'}

def main():
 assert os.environ.get('SLURM_JOB_ID')
 completion=read(RUN/'completion.json');assert completion['success']
 study=RUN/'study'/completion['experiment_id'];audit=RUN/'audit'/completion['experiment_id']
 roots=[study/r['experiment_dir'] for r in read(study/'study.json')['records'] if r['condition_id'].endswith('red-team-trace')]
 rows=[];failures=[];seen=set();seed_ids=set()
 for p in (RUN/'inputs/seeds').glob('**/usage.json'):
  v=read(p).get('call',{});seed_ids.add(v.get('response_id'))
 for root in roots:
  for p in (root/'trace-defense-requests').glob('*/attempt-*.json'):
   a=read(p);out=a.get('output')
   if out:
    g=out['generation'];r=model_receipt(a['stage'],g['requested_model'],g['provider'],g.get('usage'),p,g.get('response_id'),status=a['status'],wall_seconds=a.get('wall_seconds'),arm='user' if root.name.startswith('user') else 'full')
    r['native_cost']=out['cost'];rows.append(r)
   else:failures.append({'stage':a['stage'],'path':str(p),'error_type':a.get('error_type'),'wall_seconds':a.get('wall_seconds'),'status':a['status']})
  for p in (root/'judgments').glob('**/usage.json'):
   g=read(p).get('call') or {};rid=g.get('response_id')
   if not rid or rid in seen:continue
   seen.add(rid);rows.append(model_receipt('optimizer_judge',g['requested_model'],g['provider'],g.get('raw_usage'),p,rid,reused_frozen=rid in seed_ids))
  for p in list((root/'feedback-generations').glob('**/*.json'))+list((root/'feedback-history-summaries').glob('**/*.json')):
   v=read(p);g=v.get('feedback_generation') or v.get('summary_generation') or v.get('generation')
   if not isinstance(g,dict) or not g.get('response_id') or g['response_id'] in seen:continue
   seen.add(g['response_id']);rows.append(model_receipt('common_simulator_history_summary' if 'summary_generation' in v else 'common_simulator',g['requested_model'],g['provider'],g.get('usage') or g.get('provider_metadata',{}).get('usage'),p,g['response_id']))
 imported=set()
 for p in audit.glob('*/imported-requests.jsonl'):
  for line in p.open():imported.add((p.parent.name,json.loads(line)['key']))
 for p in (audit/'rubric_score/records').glob('*.json'):
  r=read(p);u=Path(r['evaluation_path']).parent/'usage.json';g=read(u)['call'];rid=g.get('response_id')
  if rid in seen:continue
  seen.add(rid);rows.append(model_receipt('audit_rubric',g['requested_model'],g['provider'],g.get('raw_usage'),u,rid,reused_frozen=('rubric_score',p.stem) in imported))
 for stage in ('absolute_score','pairwise_preference'):
  for p in (audit/stage/'records').glob('*.json'):
   r=read(p);g=r['generation'];rid=g.get('response_id')
   if rid in seen:continue
   seen.add(rid);rows.append(model_receipt('audit_'+stage,g['requested_model'],g['provider'],g.get('provider_metadata',{}).get('usage'),p,rid,reused_frozen=(stage,p.stem) in imported))
 for p in audit.glob('direct_*/evaluations/*/cases/*/*/score.json'):
  r=read(p)
  for item in r.get('generations',[]):
   g=item['generation'];rid=g.get('response_id')
   if rid in seen:continue
   seen.add(rid);rows.append(model_receipt('audit_'+p.parents[5].name,g['requested_model'],g['provider'],g.get('provider_metadata',{}).get('usage'),p,rid,chunk_stage=item.get('stage')))
 agent_rows=[];agents=[]
 for stage,paths in [('sidecar',[p for root in roots for p in (root/'red-team').glob('checkpoint-*/trajectory.stream.jsonl')]),
                     ('solver',[p for root in roots for p in (root/'turns').glob('turn-*/trajectory.stream.jsonl')])]:
  data,summary=stream_receipts(paths,stage);agent_rows+=data;agents.append(summary)
 owners=[read(p) for p in (RUN/'owners').glob('*/launch.json')];job_ids={str(o['job']) for o in owners};hosts={o['host'] for o in owners}
 from datetime import datetime,timezone
 earliest=min(datetime.strptime(o['time'],'%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp() for o in owners)
 events=[];coordination=Path('/home/aydanh/repos/rubric_gen/runs/.runtime-babel')
 for host in hosts:
  for p in coordination.glob(f'events-{host}-*.jsonl'):
   if p.stat().st_mtime<earliest:continue
   for line in p.open():
    try:v=json.loads(line)
    except ValueError:continue
    if str(v.get('job_id')) in job_ids:events.append(v)
 operation=defaultdict(list)
 for e in events:
  if e['event'].startswith('operation_'):operation[e['operation']].append(e)
 operations={k:{'records':len(v),'status':dict(Counter(e['event'] for e in v)),'elapsed_seconds':sum(e.get('elapsed_seconds',0) for e in v)} for k,v in operation.items()}
 leases={};max_active=active=0;wait=[]
 for e in sorted(events,key=lambda e:e['time']):
  if e.get('kind')!='provider':continue
  if e['event']=='acquired':leases[e['lease_id']]=e;active+=e['slots'];wait.append(e['wait_seconds']);max_active=max(max_active,active)
  elif e['event']=='released':active-=e['slots']
 stage_events=[]
 for owner in owners:
  logfile=ROOT/'experiments/trace-attack-defense-v1'/f"production-{owner['job']}.log"
  if not logfile.exists():continue
  content=logfile.read_text(errors='replace');position=0;decoder=json.JSONDecoder()
  while True:
   position=content.find('{"stage":',position)
   if position<0:break
   try:value,end=decoder.raw_decode(content[position:])
   except ValueError:position+=1;continue
   if value.get('stage') in ('counted_smoke','complete_120','audit','complete'):stage_events.append(value)
   position+=end
 final_time=(RUN/'completion.json').stat().st_mtime
 first_audit=min((datetime.fromisoformat(e['time']).timestamp() for e in stage_events if e['stage']=='audit' and 'time' in e),default=None)
 elapsed={'first_launch_utc':datetime.fromtimestamp(earliest,timezone.utc).isoformat(),'completion_file_mtime_utc':datetime.fromtimestamp(final_time,timezone.utc).isoformat(),
  'cohort_and_audit_seconds':final_time-earliest,'revision_stage_seconds':first_audit-earliest if first_audit else None,
  'audit_stage_seconds':final_time-first_audit if first_audit else None,'stage_events':stage_events}
 group=defaultdict(list)
 for r in rows:group[r['stage'],r['model']].append(r)
 summary=[]
 for (stage,model),rs in sorted(group.items()):
  fresh=[r for r in rs if not r.get('reused_frozen')]
  summary.append({'stage':stage,'model':model,'saved_response_records':len(rs),'reused_frozen':len(rs)-len(fresh),'fresh_saved_responses':len(fresh),
    'usage_available':sum(r['usage_available'] for r in fresh),'input_tokens':sum(r.get('input_tokens',0) for r in fresh),'output_tokens':sum(r.get('output_tokens',0) for r in fresh),
    'cached_input_tokens':sum(r.get('cached_input_tokens',0) for r in fresh),'cache_write_input_tokens':sum(r.get('cache_write_input_tokens',0) for r in fresh),
    'usage_based_usd':sum(r['usage_based_usd'] or 0 for r in fresh),'attempt_wall_seconds':sum(r.get('wall_seconds') or 0 for r in fresh)})
 table('cost-responses.csv',rows,large=True);table('cost-agent-threads.csv',agent_rows,large=True);table('cost-stage-summary.csv',summary);table('cost-failed-learning-attempts.csv',failures)
 write(OUT/'capacity-events.json',events)
 write(PUBLIC/'costs.json',{'pricing_registry_date':PRICING_AS_OF,'stages':summary,'agents':agents,'failed_learning_attempts':len(failures),'elapsed':elapsed,
  'capacity':{'operations':operations,'maximum_owned_provider_leases':max_active,'provider_wait_seconds':sum(wait),'audit_slot_wait_seconds':sum(e.get('wait_seconds',0) for e in events if e.get('kind')=='audit' and e['event']=='acquired'),'acquired_leases':len(leases),'jobs':sorted(job_ids)},
  'limitations':['Usage-based estimates are not provider invoices.','Failed calls without returned usage are counted but have unknown token cost.',
  'Persistent agent usage is cumulative: each thread contributes its maximum total, not a sum of turn totals.',
  'Native operation durations include nested operations; do not sum them as independent API calls.',
  'Stage request wall time includes capacity wait; concurrent durations are not elapsed cohort time.',
  'Internal agent model-call counts are not exposed; agent invocations/terminal events are separate from direct structured calls.',
  'Driver start wall time combines sidecars and initial solver turns; saved usage separates these channels, but their exact wall-time split is not instrumented. Resume durations are separately available in native capacity operations.'],
  'source_sha256':sha(__file__)})
 print(json.dumps({'cost_stages':len(summary),'response_records':len(rows),'agent_threads':len(agent_rows),'capacity_operations':operations}),flush=True)

if __name__=='__main__':main()
