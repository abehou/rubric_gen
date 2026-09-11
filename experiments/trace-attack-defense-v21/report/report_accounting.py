"""Read sealed cohort and native judgment plans; never creates provider requests."""
import os,json,sys
from pathlib import Path
from collections import Counter,defaultdict
from report_sources import ROOT,RUN,OUT,PUBLIC,PANEL,read,sha,write
from report_pipeline import table


def semantic_cells(stage,summary,audit,by_id):
 instrument={'absolute_score':'absolute','pairwise_preference':'pairwise'}.get(stage)
 jobs={j['semantic_key']:j for j in summary['predispatch_plan']['jobs'] if instrument is None or j['instrument']==instrument}
 assert len(jobs)==summary['planned_semantic_judgment_count']
 imported={}
 path=audit/stage/'imported-requests.jsonl'
 if path.exists():
  for line in path.open():
   value=json.loads(line);imported[value['key']]=value
 by_key=defaultdict(list)
 for record in summary['records']:
  assert record['assignment_id'] in by_id
  by_key[record['judgment_key']].append(record)
 assert set(jobs)==set(by_key)
 cells=[];receipts=[]
 for key,job in jobs.items():
  path=audit/stage/'records'/f'{key}.json';raw=read(path)
  refs=by_key[key];arms=sorted({by_id[r['assignment_id']]['arm'] for r in refs})
  receipts.append({'stage':stage,'judgment_key':key,'model':job['model'],'arms':arms,'assignment_ids':sorted({r['assignment_id'] for r in refs}),
   'assignment_reference_count':len(refs),'reused_frozen':key in imported,'record_path':str(path),'record_sha256':sha(path),
   'prompt_sha256':raw.get('prompt_sha256'),'grading_identity':raw.get('grading_identity')})
  for record in refs:
   cells.append({'stage':stage,'assignment_id':record['assignment_id'],'arm':by_id[record['assignment_id']]['arm'],
    'model':record['model'],'artifact':record.get('artifact'),'rubric_roles':record.get('rubric_roles'),
    'judgment_key':key,'required':True,'completed':True,'failed':False,'abstaining':False,
    'verdict':record.get('verdict'),'score':record.get('score'),'reused_frozen':key in imported,
    'path':str(path),'record_sha256':sha(path)})
 return cells,receipts


def main():
 assert os.environ.get('SLURM_JOB_ID')
 completion=read(RUN/'completion.json');assert completion['success']
 study=RUN/'study'/completion['experiment_id'];audit=RUN/'audit'/completion['experiment_id']
 sys.path.insert(0,str(ROOT/'scripts/diagnostics'))
 from check_audit_coverage import check,source_records
 verified=check(study,audit,expected_models=PANEL)
 records=source_records(study);assert len(records)==120
 by_id={r['assignment_id']:{**r,'arm':'user' if r['condition_id'].startswith('user') else 'full'} for r in records}
 cells=[];receipts=[];summaries={}
 for stage in ('rubric_score','absolute_score','pairwise_preference'):
  path=audit/stage/'summary.json';summary=read(path)
  summaries[stage]={'path':str(path),'sha256':sha(path),'assignment_coverage':summary['assignment_coverage'],
   'planned_unique':summary['planned_semantic_judgment_count'],'completed_unique':summary['successful_semantic_judgment_count'],
   'failed_unique':summary['failed_semantic_judgment_count'],'judge_failures':summary['judge_failures'],'missing_models':summary['missing_models']}
  cs,rs=semantic_cells(stage,summary,audit,by_id);cells.extend(cs);receipts.extend(rs)
 paths={str(study/r['experiment_dir']):r['assignment_id'] for r in records}
 for window in ('full_trajectory','post_update','final_artifact','final_revision'):
  stage='direct_'+window;matches=list((audit/stage/'evaluations').glob('*/summary.json'));assert len(matches)==1
  summary=read(matches[0]);summaries[stage]={'path':str(matches[0]),'sha256':sha(matches[0]),'planned_unique':120*len(PANEL),'completed_unique':len(summary['records']),'failed_unique':0}
  for r in summary['records']:
   aid=paths[r['source_path']];path=matches[0].parent/'cases'/r['case_id']/r['model']/'score.json';raw=read(path)
   assert raw['status']=='completed'
   key=r['case_id']+'::'+r['model'];decision=r['verdict']['decision']
   row={'stage':stage,'assignment_id':aid,'arm':by_id[aid]['arm'],'model':r['model'],
    'judgment_key':key,'required':True,'completed':True,'failed':False,'abstaining':decision=='abstain',
    'verdict':decision,'monitor_score':r['verdict'].get('score'),'reused_frozen':False,'path':str(path),'record_sha256':sha(path)}
   cells.append(row);receipts.append({**row,'arms':[by_id[aid]['arm']],'assignment_ids':[aid],'assignment_reference_count':1})
 assignments=[]
 for aid,r in by_id.items():
  root=study/r['experiment_dir'];state=read(root/'state.json');manifest=read(root/'manifest.json')
  own=[c for c in cells if c['assignment_id']==aid];keys={(c['stage'],c['judgment_key']) for c in own}
  turns=sorted((root/'turns').glob('turn-*/prompt.txt'));bindings=sorted((root/'submission-rubric-bindings').glob('s*.json'))
  assignments.append({'assignment_id':aid,'task_id':r['task_id'],'replicate':r['replicate'],'arm':r['arm'],
   'expected_assignment':1,'completed_assignment':r['status']=='completed','solver_turns':len(turns),'retained_revisions':len(state['submission_ids'])-1,
   'minimum_revisions':manifest['min_revisions'],'maximum_revisions':manifest['max_revisions'],'stop_reason':state['stop_reason'],
   'required_judgment_references':len(own),'completed_judgment_references':sum(c['completed'] for c in own),
   'required_unique_judgments_for_assignment':len(keys),'abstaining_references':sum(c['abstaining'] for c in own),'missing':0,'failed':0,
   'reused_judgment_references':sum(c['reused_frozen'] for c in own),'manifest_path':str(root/'manifest.json'),
   'manifest_sha256':sha(root/'manifest.json'),'state_sha256':sha(root/'state.json'),
   'input_identity':{k:v for k,v in manifest.items() if k.endswith('_sha256') or k in ('model','reasoning_effort','temperature','red_team_trace_version')},
   'solver_prompt_sha256s':[sha(p) for p in turns],'binding_sha256s':[read(p)['binding_sha256'] for p in bindings]})
 by_arm={}
 for arm in ('full','user'):
  own=[a for a in assignments if a['arm']==arm];cs=[c for c in cells if c['arm']==arm];rs=[r for r in receipts if arm in r['arms']]
  by_arm[arm]={'expected_assignments':60,'completed_assignments':sum(a['completed_assignment'] for a in own),
   'solver_turns':sum(a['solver_turns'] for a in own),'retained_revisions':sum(a['retained_revisions'] for a in own),
   'required_judgment_references':len(cs),'completed_judgment_references':len(cs),
   'required_unique_judgments_including_shared':len(rs),'completed_unique_judgments_including_shared':len(rs),
   'shared_between_arms':sum(len(r['arms'])>1 for r in rs),'reused_unique_judgments':sum(r['reused_frozen'] for r in rs),
   'abstaining_cells':sum(c['abstaining'] for c in cs),'missing_cells':0,'failed_cells':0,
   'stages':{s:{'unique':sum(r['stage']==s for r in rs),'references':sum(c['stage']==s for c in cs),'abstentions':sum(c['abstaining'] for c in cs if c['stage']==s)} for s in summaries}}
 owners=[]
 for p in sorted((RUN/'owners').glob('*/launch.json')):
  owners.append({'path':str(p),'sha256':sha(p),'launch':read(p),'receipts':[{'path':str(q),'sha256':sha(q),'record':read(q)} for q in sorted(p.parent.glob('*.json')) if q!=p]})
 assert len(receipts)==verified['semantic_judgments']
 table('assignment-accounting.csv',assignments);table('judgment-cells.csv',cells,large=True);table('judgment-receipts.csv',receipts,large=True)
 write(OUT/'assignment-accounting.json',assignments)
 freeze=ROOT/'experiments/trace-attack-defense-v21/execution-freeze.json'
 result={'execution_commit':completion['commit'],'experiment_id':completion['experiment_id'],'run_root':str(RUN),
  'freeze_path':str(freeze),'freeze_sha256':sha(freeze),'freeze':read(freeze),'native_coverage':verified,'arms':by_arm,
  'unique_judgments':len(receipts),'completed_unique_judgments':len(receipts),'shared_between_arms':sum(len(r['arms'])>1 for r in receipts),
  'stages':summaries,'owners':owners,'completion_path':str(RUN/'completion.json'),'completion_sha256':sha(RUN/'completion.json'),
  'notes':['Per-arm unique counts include shared semantic keys and therefore must not be summed without deduplication.',
   'Expected assignments are fixed at 60 per arm; solver revision counts follow the unchanged 5–10-turn/no-change stopping rules.',
   'Required judgment counts come from the sealed cohort native plans and windows, not a historical fixed total.',
   'Completed detector abstentions remain completed cells and are reported separately from missing/failed cells.']}
 write(PUBLIC/'accounting.json',result);print(json.dumps({'arms':by_arm,'unique_judgments':len(receipts)}),flush=True)

if __name__=='__main__':main()
