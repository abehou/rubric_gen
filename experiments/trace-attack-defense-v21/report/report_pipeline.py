"""Read-only lifecycle, timing and learning-call accounting; no provider imports."""
import json,csv,os,hashlib
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor
from statistics import mean,median
from report_sources import ROOT,RUN,PUBLIC,OUT,read,sha,write

def table(name,rows,*,large=False):
 fields=list(dict.fromkeys(k for row in rows for k in row))
 destination=(OUT if large else PUBLIC)/name
 destination.parent.mkdir(parents=True,exist_ok=True)
 with destination.open('w') as f:
  writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader()
  for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else v for k,v in row.items()})
 if large:
  receipt=PUBLIC/'raw-table-receipts.json'
  payload=read(receipt) if receipt.exists() else {}
  payload[name]={'path':str(destination),'rows':len(rows),'bytes':destination.stat().st_size,'sha256':sha(destination)}
  write(receipt,payload)

def distribution(values):
 values=[x for x in values if x is not None]
 return {'n':len(values),'mean':mean(values) if values else None,'median':median(values) if values else None,'histogram':dict(sorted(Counter(values).items()))}

def contract_errors(record):
 """Read v2/v2.1 saved error fields without treating a valid negative as failure."""
 return record.get('source_errors') or record.get('validation_errors') or []

def collect(root):
 state=read(root/'state.json');manifest=read(root/'manifest.json')
 base={k:manifest[k] for k in ('assignment_id','task_id','replicate','condition_id')}
 base['arm']='user' if base['condition_id'].startswith('user') else 'full'
 generations=[];relations=[];attacks=[];deliveries=[];failures=[];requests=[];rules=[]
 for p in sorted((root/'rubric-generations').glob('generation-*/manifest.json')):
  g=read(p);number=g['generation_round'];directory=p.parent
  for name,digest in g['file_sha256s'].items():assert sha(directory/name)==digest
  active=read(directory/'criteria.json')
  for c in active:
   if c['source_generation']==number:rules.append({**base,'generation':number,**c,'generation_sha256':g['generation_sha256'],'path':str(directory/'criteria.json')})
  if number==0:continue
  ev=read(directory/'evolution.json');proposal=read(directory/'criterion-proposal.json');validation=read(directory/'criterion-validation.json');admission=read(directory/'aggregate-margins.json')
  comparisons=read(directory/'pairwise-comparisons.json')['comparisons'];pairs={p['pair_id']:p for p in comparisons}
  decisions=admission['decisions'];counter=Counter('accepted' if d['accepted'] else d['reason'] for d in decisions)
  row={**base,'generation':number,'source_checkpoint':g['source_checkpoint'],'offline':number==1,'path':str(directory),'generation_sha256':g['generation_sha256'],
       'proposed':len(proposal['criteria']),'admitted':len(admission['accepted_candidate_ids']),'decisions':dict(counter),'active_criteria':len(active),
       'quality_ordered_pairs':len(comparisons),'gap_pairs':sum(bool(p['gap_views']) for p in comparisons),'logical_call_ceiling':ev.get('logical_call_ceiling'),
       'call_budget':g['proposer_call_budget'],'logical_requests':ev.get('logical_requests'),'recorded_new_calls':ev.get('actual_calls'),'recorded_cache_hits':ev.get('cache_hits')}
  if number>=2:
   assert g['source_checkpoint']==number-2 and g['source_schedule']=='pre_revision_v1'
   quality=read(directory/'pairwise-assessment-rubric-free.json')['pairs']
   row['quality_source_failure_pairs']=sum(bool(contract_errors(q)) for q in quality)
   row['quality_no_order_pairs']=sum(q['response'] is not None and q['response']['preferred_artifact_id'] is None for q in quality)
   row['quality_unavailable_pairs']=sum(q['response'] is None for q in quality)
   row['compilation_empty']=sum(c['response'] is not None and not c['response']['criteria'] for c in proposal['compilations'])
   row['compilation_unavailable']=sum(c['response'] is None for c in proposal['compilations'])
   diags=proposal['diagnoses'];row['selected_pairs']=proposal['selection'];row['diagnoses']=dict(Counter((d['response'].get('action') if d['response'] else 'unavailable') for d in diags))
   row['supported_diagnoses']=sum(d['response'] is not None and (d['response'].get('action')=='ADD' or str(d['response'].get('action','')).startswith('REPLACE:')) and not contract_errors(d) for d in diags)
   row['diagnosis_quote_failures']=sum(bool(contract_errors(d)) for d in diags)
   for f in validation['ineligibility']:failures.append({**base,'generation':number,**f,'path':str(directory/'criterion-validation.json')})
   row['failure_records']=len(validation['ineligibility'])
   proposed_by_pair={c['provenance_pair_ids'][0]:c for c in proposal['criteria']}
   # Actual witness application levels are independent observations; predicted
   # levels remain a separate diagnostic and never determine admission.
   byid={c['criterion_id']:c for c in active if c['source_generation']==number}
   for review in validation['reviews']:
    cid=review['criterion_id'];applications={x['artifact_id']:x for x in review['applications']}
    decision=next((d for d in decisions if d['criterion_id']==cid),None)
    witness=(byid.get(cid) or {}).get('provenance_pair_ids')
    if witness is None:
     from rubric_gen.submission_revision.rubric_generation import ElicitedCriterion
     for raw in proposal['criteria']:
      points=(0,-5,-10)
      try:c=ElicitedCriterion.create(title=raw['title'],requirement=raw['requirement'],levels=tuple((x['label'],points[i],x['description']) for i,x in enumerate(raw['levels'])),provenance_pair_ids=tuple(raw['provenance_pair_ids']),source_generation=number)
      except ValueError:continue
      if c.criterion_id==cid:witness=raw['provenance_pair_ids'];break
    assert witness is not None and len(witness)==1
    pair=pairs[witness[0]];a=applications[pair['preferred_artifact_id']];b=applications[pair['rejected_artifact_id']]
    la=a['response']['level'] if a['response'] else None;lb=b['response']['level'] if b['response'] else None
    compiled=next((c['response'] for c in proposal['compilations'] if c['pair_id']==witness[0]),None)
    relations.append({**base,'generation':number,'criterion_id':cid,'pair_id':witness[0],
       'preferred_level':la,'rejected_level':lb,'independent_relation':f'{la}/{lb}',
       'predicted_levels':compiled.get('predicted_levels') if compiled else None,'semantic':review['semantic'],
       'required_applications':len(review['applications']),'quoted_application_spans':sum(len((x['response'] or {}).get('public_evidence',(x['response'] or {}).get('public_refs',[]))) for x in review['applications']),
       'accepted':bool(decision and decision['accepted']),'rejection_reason':decision['reason'] if decision else 'structural_candidate_ineligible',
       'ineligibility':review['ineligibility'],'application_source_errors':sum(bool(contract_errors(x)) for x in review['applications']),
       'path':str(directory/'criterion-validation.json')})
  generations.append(row)
 for p in sorted((root/'red-team').glob('checkpoint-*/manifest.json')):
  m=read(p)
  record_name='attack-record-v2.json' if (p.parent/'attack-record-v2.json').is_file() else 'attack-record.json'
  record=read(p.parent/record_name);status=read(p.parent/'status.json')
  assert sha(p.parent/record_name)==m['file_sha256s'][record_name]
  attacks.append({**base,'checkpoint':m['checkpoint'],'included':m['included'],'public_nonidentical':record['public_nonidentical'],
    'narration_available':record['narration_available'],'narrated_status':(record['narration'] or {}).get('status'),
    'quote_failures':record.get('source_validation_errors', record.get('parse_errors', [])),'actual_changed_files':record['actual_changed_files'],
    'exit_code':status.get('exit_code'),'attempt_count':status.get('attempt_count',1),
    'source_public_sha256':record['source_public_sha256'],'output_public_sha256':record['output_public_sha256'],
    'record_path':str(p.parent/record_name),'record_sha256':sha(p.parent/record_name)})
 for p in sorted((root/'trace-defense-reminders').glob('s*.json')):
  r=read(p);s=r['submission_id'];turn=root/'turns'/f"turn-{r['solver_turn']:03d}"/'prompt.txt'
  assert turn.is_file() and sha(turn)==r['final_prompt_sha256']
  binding=read(root/'submission-rubric-bindings'/p.name);ev=read(root/'rubric-evaluations'/p.name)
  assert binding['active_generation_sha256']==r['generation_sha256'] and binding['solver_turn']==r['solver_turn']
  selection=r['selection']
  deliveries.append({**base,'submission_id':s,'source_checkpoint':binding['source_checkpoint'],'active_generation':binding['active_generation_round'],
    'solver_turn':r['solver_turn'],'exposed':selection is not None,'category':selection['category'] if selection else None,
    'corrective':selection['corrective'] if selection else None,'criterion_id':selection['criterion_id'] if selection else None,
    'criterion_source_generation':selection['source_generation'] if selection else None,'points':selection['points'] if selection else None,
    'previously_reminded':selection['previously_reminded'] if selection else None,'skipped':r['skipped'],
    'reminder_component_bytes':len(r['message_component'].encode()),'reminder_component_chars':len(r['message_component']),'solver_prompt_bytes':turn.stat().st_size,
    'elicited_penalty':ev['elicited_penalty'],'W':ev['reference_score'],'W_train':ev['score'],
    'prompt_path':str(turn),'prompt_sha256':sha(turn),'binding_sha256':binding['binding_sha256'],'receipt_path':str(p)})
 for p in sorted((root/'trace-defense-requests').glob('*/attempt-*.json')):
  a=read(p);output=a.get('output') or {};generation=output.get('generation') or {};cost=output.get('cost') or {}
  requests.append({**base,'stage':a['stage'],'request_sha256':a['request_sha256'],'attempt':a['attempt'],'status':a['status'],
      'wall_seconds':a.get('wall_seconds'),'model':generation.get('requested_model'),'usage':generation.get('usage'),**cost,
      'error_type':a.get('error_type'),'error':a.get('error'),'path':str(p),'sha256':sha(p)})
 online=[g for g in generations if not g['offline']]
 admissions=[g['generation'] for g in online if g['admitted']]
 reminders=[d for d in deliveries if d['exposed']]
 lifecycle={**base,'root':str(root),'retained_revisions':len(state['submission_ids'])-1,'solver_turns':len(list((root/'turns').glob('turn-*'))),'stop_reason':state['stop_reason'],
   'online_updates':len(online),'online_proposed':sum(g['proposed'] for g in online),'online_admitted':sum(g['admitted'] for g in online),
   'first_online_admission':min(admissions,default=None),'first_reminder_turn':min((d['solver_turn'] for d in reminders),default=None),
   'pre_turn1_online_admission':2 in admissions,'pre_turn1_reminder':any(d['solver_turn']==1 for d in reminders),
   'proactive_reminders':sum(not d['corrective'] for d in reminders),'corrective_reminders':sum(d['corrective'] for d in reminders),
   'penalized_feedback_opportunities':sum(d['elicited_penalty']<0 for d in deliveries),
   'learning_attempts':len(requests),'learning_provider_failures':sum(r['status']=='provider_failure' for r in requests),
   'manifest_sha256':sha(root/'manifest.json'),'state_sha256':sha(root/'state.json')}
 return {'lifecycle':lifecycle,'generations':generations,'relations':relations,'attacks':attacks,'deliveries':deliveries,'failures':failures,'requests':requests,'rules':rules}

def main():
 assert os.environ.get('SLURM_JOB_ID')
 # Learning records are sealed when all revisions complete; their inspection
 # does not depend on outcome audits or supply evidence to those audits.
 studies=list((RUN/'study').glob('*/study.json'));assert len(studies)==1
 study=studies[0].parent;ledger=read(studies[0])
 chosen=[r for r in ledger['records'] if r['condition_id'].endswith('red-team-trace')]
 assert len(chosen)==120 and all(r['status']=='completed' for r in chosen)
 with ThreadPoolExecutor(max_workers=4) as pool:cases=list(pool.map(collect,[study/r['experiment_dir'] for r in chosen]))
 write(OUT/'pipeline-cases.json',cases)
 for name in ('lifecycle','generations','relations','attacks','deliveries','failures','requests','rules'):
  rows=[c[name] for c in cases] if name=='lifecycle' else [r for c in cases for r in c[name]]
  table('pipeline-'+name+'.csv',rows,large=name=='requests')
 summary={}
 for arm in ('full','user'):
  cs=[c for c in cases if c['lifecycle']['arm']==arm];life=[c['lifecycle'] for c in cs];gs=[g for c in cs for g in c['generations'] if not g['offline']];attacks=[a for c in cs for a in c['attacks']];ds=[d for c in cs for d in c['deliveries']]
  summary[arm]={'assignments':len(cs),'any_online_proposal':sum(x['online_proposed']>0 for x in life),'any_online_admission':sum(x['online_admitted']>0 for x in life),
    'online_proposed':sum(x['online_proposed'] for x in life),'online_admitted':sum(x['online_admitted'] for x in life),'attacks_attempted':len(attacks),
    'attacks_valid_execution':sum(a['included'] for a in attacks),'attacks_nonidentical':sum(a['public_nonidentical'] for a in attacks),
    'attacks_narrated_created':sum(a['narrated_status']=='attack_created' for a in attacks),'attack_narration_or_quote_failures':sum(bool(a['quote_failures']) for a in attacks),
    'attack_literal_quote_failures':sum(any('literal public quote not found' in e for e in a['quote_failures']) for a in attacks),
    'quality_source_failure_update_pairs':sum(g['quality_source_failure_pairs'] for g in gs),
    'quality_no_order_update_pairs':sum(g['quality_no_order_pairs'] for g in gs),
    'quality_unavailable_update_pairs':sum(g['quality_unavailable_pairs'] for g in gs),
    'empty_compilations':sum(g['compilation_empty'] for g in gs),'unavailable_compilations':sum(g['compilation_unavailable'] for g in gs),
    'diagnosis_source_failures':sum(g['diagnosis_quote_failures'] for g in gs),
    'quality_order_gap_update_pairs':sum(g['gap_pairs'] for g in gs),'supported_diagnoses':sum(g['supported_diagnoses'] for g in gs),
    'preference_conflicts':sum(g['diagnoses'].get('preference_conflict',0) for g in gs),
    'independent_witness_relations':dict(Counter(r['independent_relation'] for c in cs for r in c['relations'])),
    'semantic_reviews':sum(len(c['relations']) for c in cs),
    'semantic_unobservable':sum(r['semantic'] is not None and not r['semantic']['observable'] for c in cs for r in c['relations']),
    'semantic_redundant':sum(r['semantic'] is not None and not r['semantic']['nonredundant'] for c in cs for r in c['relations']),
    'required_candidate_applications':sum(r['required_applications'] for c in cs for r in c['relations']),
    'native_decisions':dict(sum((Counter(g['decisions']) for g in gs),Counter())),
    'structural_failure_records':dict(Counter(f['stage']+':'+f['reason'] for c in cs for f in c['failures'])),
    'validation_ineligibility_details':dict(Counter(d['reason'] for c in cs for f in c['failures'] for d in f.get('details',[]))),
    'first_online_admission':distribution(x['first_online_admission'] for x in life),'first_reminder_turn':distribution(x['first_reminder_turn'] for x in life),
    'pre_turn1_online_admission':sum(x['pre_turn1_online_admission'] for x in life),'pre_turn1_reminder':sum(x['pre_turn1_reminder'] for x in life),
    'reminder_component_bytes':sum(d['reminder_component_bytes'] for d in ds),
    'reminder_component_chars':sum(d['reminder_component_chars'] for d in ds),
    'proactive_reminders':sum(x['proactive_reminders'] for x in life),'corrective_reminders':sum(x['corrective_reminders'] for x in life),
    'reminder_skips':dict(Counter(s['reason'] for d in ds for s in d['skipped'])),
    'solver_turns':sum(x['solver_turns'] for x in life),'learning_actual_attempts':sum(x['learning_attempts'] for x in life),
    'learning_provider_failures':sum(x['learning_provider_failures'] for x in life),
    'early_update_actual_calls':sum(g['recorded_new_calls'] for g in gs if g['generation']==2),
    'early_update_cache_hits':sum(g['recorded_cache_hits'] for g in gs if g['generation']==2),
    'all_update_cache_hits':sum(g['recorded_cache_hits'] for g in gs),
    'logical_call_ceiling_total':sum(g['logical_call_ceiling'] for g in gs),
    'bounded_attempt_ceiling_total':sum(g['call_budget'] for g in gs),
    'offline_proposed_assignment_copies':sum(g['proposed'] for c in cs for g in c['generations'] if g['offline']),
    'offline_admitted_assignment_copies':sum(g['admitted'] for c in cs for g in c['generations'] if g['offline']),
    'offline_unique_generation_hashes':sorted({g['generation_sha256'] for c in cs for g in c['generations'] if g['offline']})}
 write(PUBLIC/'pipeline-summary.json',summary);print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
