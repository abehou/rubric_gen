"""Saved learned-rule availability, prompt exposure, and subsequent scored levels."""
import os,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict,Counter
from report_sources import RUN,OUT,PUBLIC,read,sha,write
from report_pipeline import table,distribution


def one(case):
 life=case['lifecycle'];root=Path(life['root']);base={k:life[k] for k in ('arm','assignment_id','task_id','replicate')}
 validations={sha(p):p for p in (root/'judgments').glob('**/score_validation.json')}
 prompts=[(int(p.parent.name.split('-')[-1]),p,p.read_text()) for p in sorted((root/'turns').glob('turn-*/prompt.txt'))]
 reminders=[r for r in case['deliveries'] if r['exposed']]
 observations=[];rules={};all_generations={}
 for p in sorted((root/'submission-rubric-bindings').glob('s*.json')):
  binding=read(p);sid=binding['submission_id'];checkpoint=int(sid[1:]);g=binding['active_generation_round']
  gd=root/'rubric-generations'/f'generation-{g:04d}'
  if g not in all_generations:all_generations[g]=read(gd/'criteria.json')
  criteria=all_generations[g];ev=read(root/'rubric-evaluations'/p.name)
  vpath=validations[ev['score_validation_sha256']];validation=read(vpath);scores=validation['criterion_scores'];levels=validation['criterion_levels']
  offset=len(scores)-len(criteria)+1
  for index,c in enumerate(criteria,offset):
   cid=c['criterion_id'];rules[cid]=c;native_id=f'criterion_{index}';points=scores[native_id]
   past=[r for r in reminders if r['criterion_id']==cid and r['solver_turn']<=checkpoint]
   current=next((r for r in reminders if r['criterion_id']==cid and r['submission_id']==sid),None)
   observations.append({**base,'submission_id':sid,'active_generation':g,'criterion_id':cid,'criterion_source_generation':c['source_generation'],
    'native_level':levels[native_id],'points':points,'scored_violation':points<0,
    'feedback_opportunity':binding['feedback_opportunity'],'eventual_solver_turn':binding['solver_turn'],
    'reminded_before_this_submission':bool(past),'prior_reminder_turns':[r['solver_turn'] for r in past],
    'reminded_for_next_turn':bool(current),'next_reminder_category':current['category'] if current else None,
    'validation_path':str(vpath),'validation_sha256':ev['score_validation_sha256'],'binding_sha256':binding['binding_sha256']})
 timeline=[]
 for cid,c in rules.items():
  obs=[r for r in observations if r['criterion_id']==cid];ds=[r for r in reminders if r['criterion_id']==cid]
  opportunities=[r['eventual_solver_turn'] for r in obs if r['feedback_opportunity']]
  first_possible=min(opportunities,default=None);first_reminder=min((r['solver_turn'] for r in ds),default=None)
  exposures=[]
  for turn,path,text in prompts:
   if first_possible is None or turn<first_possible:continue
   for representation,requirement in [('literal',c['requirement']),('json_escaped',json.dumps(c['requirement'],ensure_ascii=False)[1:-1])]:
    if requirement in text:
     exposures.append({'turn':turn,'path':str(path),'sha256':sha(path),'offset':text.index(requirement),'representation':representation});break
  followup=[r for r in obs if r['reminded_before_this_submission']]
  timeline.append({**base,'criterion_id':cid,'source_generation':c['source_generation'],'offline':c['source_generation']==1,
   'first_scored_submission':obs[0]['submission_id'],'first_available_feedback_turn':first_possible,
   'first_focused_reminder_turn':first_reminder,'availability_to_reminder_lag':first_reminder-first_possible if first_reminder is not None and first_possible is not None else None,
   'first_verbatim_requirement_turn':exposures[0]['turn'] if exposures else None,'verbatim_requirement_exposures':exposures,
   'reminder_deliveries':len(ds),'proactive_deliveries':sum(not r['corrective'] for r in ds),'corrective_deliveries':sum(r['corrective'] for r in ds),
   'scored_observations':len(obs),'scored_violations':sum(r['scored_violation'] for r in obs),
   'post_reminder_scored_observations':len(followup),'post_reminder_scored_violations':sum(r['scored_violation'] for r in followup),
   'post_reminder_violation_response_opportunities':sum(r['scored_violation'] and r['feedback_opportunity'] for r in followup),
   'first_post_reminder_level':followup[0]['native_level'] if followup else None,
   'first_post_reminder_points':followup[0]['points'] if followup else None})
 return observations,timeline


def main():
 assert os.environ.get('SLURM_JOB_ID')
 cases=read(OUT/'pipeline-cases.json');assert len(cases)==120
 assert all(sha(Path(c['lifecycle']['root'])/'state.json')==c['lifecycle']['state_sha256'] for c in cases)
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(one,cases))
 observations=[r for a,b in results for r in a];rules=[r for a,b in results for r in b]
 table('timing-scored-rules.csv',observations,large=True);table('timing-rule-lineage.csv',rules)
 summary={}
 for arm in ('full','user'):
  rs=[r for r in rules if r['arm']==arm];obs=[o for o in observations if o['arm']==arm]
  summary[arm]={'active_rule_lineages':len(rs),'reminded_lineages':sum(r['reminder_deliveries']>0 for r in rs),
   'lineages_with_verbatim_requirement_exposure':sum(r['first_verbatim_requirement_turn'] is not None for r in rs),
   'online_lineages_with_verbatim_requirement_exposure':sum(not r['offline'] and r['first_verbatim_requirement_turn'] is not None for r in rs),
   'availability_to_reminder_lag':distribution(r['availability_to_reminder_lag'] for r in rs),
   'scored_violations':sum(o['scored_violation'] for o in obs),'post_reminder_scored_observations':sum(o['reminded_before_this_submission'] for o in obs),
   'post_reminder_scored_violations':sum(o['scored_violation'] and o['reminded_before_this_submission'] for o in obs),
   'post_reminder_violation_response_opportunities':sum(o['scored_violation'] and o['reminded_before_this_submission'] and o['feedback_opportunity'] for o in obs),
   'first_post_reminder_points':distribution(r['first_post_reminder_points'] for r in rs)}
 write(PUBLIC/'timing-summary.json',{'arms':summary,'limitations':[
  'Availability/exposure is observed from persisted generation bindings and actual solver prompts; it is not compliance.',
  'Subsequent levels are weak optimizer judgments, not independent RH verification.',
  'A no-change solver turn may end without a new sealed submission or subsequent score observation.',
  'Focused reminders are exact exposures; ordinary Full/User feedback can also convey overlapping checks.',
  'Verbatim requirements include exact literal or JSON-escaped matches in real prompts; absence does not rule out a paraphrased check in ordinary feedback.',
  'Rule-observation counts repeat a lineage across submissions and are not independent assignments.']})
 print(summary,flush=True)

if __name__=='__main__':main()
