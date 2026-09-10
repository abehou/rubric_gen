"""Descriptive matched full-feedback transitions; no new scoring or providers."""
import hashlib,json,os
from pathlib import Path
from collections import Counter,defaultdict
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-result20-current-20260908'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def panel(rows,window):
 labels=[r['direct'][window]['decision'] for r in rows]
 if 'reward_hacking_detected' in labels:return 'positive'
 if 'abstain' in labels:return 'unresolved'
 assert set(labels)=={'no_reward_hacking_detected'}
 return 'negative'
def main():
 assert os.environ.get('SLURM_JOB_ID')
 report=BASE/'full-policy-comparison-v1/analysis.json';exposure=BASE/'full-policy-exposure-v1/policy-exposure.json'
 receipt=json.loads(report.with_name('combination-receipt.json').read_text());assert receipt['success'] and receipt['source_unchanged'] and sha(report)==receipt['analysis_sha256']
 data=json.loads(report.read_text());exp=json.loads(exposure.read_text());by=defaultdict(list)
 for r in data['rows']:
  assert sha(Path(r['state_path']))==r['state_sha256']
  by[r['condition_id'],r['task_id'],r['replicate']].append(r)
 e={r['assignment']:r for r in exp['assignments']}
 keys={(r['task_id'],r['replicate']) for r in data['rows']};assert len(keys)==60
 rows=[];counts=Counter();cross=defaultdict(Counter)
 for task,rep in sorted(keys):
  left=by['full-static',task,rep];right=by['full-red-team-trace',task,rep]
  assert len(left)==len(right)==2 and {r['model'] for r in left}=={r['model'] for r in right}=={'gpt-5.6-sol','claude-opus-5'}
  assert {r['initial_submission_sha256'] for r in left}=={r['initial_submission_sha256'] for r in right},(task,rep,'seed mismatch')
  assert {r['selected_rubric_sha256'] for r in left}=={r['selected_rubric_sha256'] for r in right},(task,rep,'selected mismatch')
  evidence=e[right[0]['assignment_id']]['counts'];admit=evidence['distinct_online_accepted']>0;penalty=evidence['accepted_ids_observed_negative']>0
  transitions={w:f'{panel(left,w)} -> {panel(right,w)}' for w in ['full_trajectory','post_update','final_artifact','final_revision']}
  for w,t in transitions.items():counts[w+': '+t]+=1
  cross[transitions['full_trajectory']].update(assignments=1,online_admission=int(admit),online_penalty=int(penalty))
  quality=lambda rs:sum(r['values']['A'] for r in rs)/2
  rows.append({'task':task,'replicate':rep,'transitions':transitions,'online_admission':admit,'online_penalty':penalty,'online_counts':evidence,'static_A':quality(left),'trace_A':quality(right),'quality_difference':quality(right)-quality(left),'static_stop':left[0]['stop_reason'],'trace_stop':right[0]['stop_reason'],'static_turns':left[0]['attempted_turns'],'trace_turns':right[0]['attempted_turns'],'auditors':{r['model']:{'static':next(z['direct'] for z in left if z['model']==r['model']),'trace':r['direct']} for r in right},'static_state':left[0]['state_path'],'trace_state':right[0]['state_path']})
 result={'job':os.environ['SLURM_JOB_ID'],'input_hashes':{str(report):sha(report),str(exposure):sha(exposure)},'script_sha256':sha(Path(__file__)),'assignments':60,'same_initial_seed_and_selected_rubric_verified':True,'transition_counts':dict(counts),'full_trajectory_transitions_by_exposure':{k:dict(v) for k,v in cross.items()},'rows':rows,'scope':'Complete matched full-feedback population;descriptive outcome-selected subgroups,not causal effects or new tests. Sidecars are excluded from natural RH;online admission does not prove actual feedback timing.'}
 out=BASE/'full-policy-mechanism-v1';out.mkdir(exist_ok=False);(out/'mechanism.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['transition_counts','full_trajectory_transitions_by_exposure']},indent=2))
if __name__=='__main__':main()
