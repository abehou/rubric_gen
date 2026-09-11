"""Assemble saved public-artifact/score evidence for gap contributors and quality losses."""
import os,csv,json
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from report_sources import RUN,OUT,PUBLIC,read,sha,write
from report_pipeline import table


def public_record(row):
 root=Path(row['state_path']).parent;workspace=root/'submissions'/row['submission_id']/'workspace'
 manifest=read(root/'manifest.json');composition=read(row['score_composition_path'])
 ref=composition['feedback_reference'];weak=root/'judgments'/row['submission_id']/ref['rubric_sha256']/'evaluation.json'
 assert sha(weak)==ref['evaluation_sha256']
 files={name:{'path':str(workspace/name),'sha256':sha(workspace/name),'text':(workspace/name).read_text()} for name in ('answer.txt','trace.md')}
 return {'root':str(root),'submission_id':row['submission_id'],'public_files':files,'composition':composition,
  'weak_judgment':read(weak),'weak_judgment_path':str(weak),'weak_judgment_sha256':sha(weak),
  'task_instruction':(Path(manifest['task_dir'])/'instruction.md').read_text(),
  'manifest_sha256':sha(root/'manifest.json'),'state_sha256':sha(root/'state.json')}


def packet(item):
 key,reasons,old,new,deltas=item
 result={'arm':key[0],'task_id':key[1],'replicate':key[2],'selection_reasons':sorted(reasons),'deltas':deltas,
  'reference':public_record(old[0]),'candidate':public_record(new[0]),'auditors':{}}
 for role,rows in [('reference',old),('candidate',new)]:
  for r in rows:
   selected=Path(r['rubric_paths'][0]);s=read(selected);sp=Path(s['evaluation_path']);a=Path(r['quality_path'])
   result['auditors'].setdefault(r['model'],{})[role]={'values':r['values'],
    'selected_judgment':read(sp),'selected_record_path':str(selected),'selected_record_sha256':sha(selected),'selected_judgment_path':str(sp),'selected_judgment_sha256':sha(sp),
    'absolute_judgment':read(a),'absolute_judgment_path':str(a),'absolute_judgment_sha256':sha(a)}
 root=Path(new[0]['state_path']).parent
 result['reminders']=[read(p) for p in sorted((root/'trace-defense-reminders').glob('s*.json'))]
 result['rules']=[{'generation':int(p.parent.name.split('-')[-1]),'criteria':read(p),'path':str(p),'sha256':sha(p)} for p in sorted((root/'rubric-generations').glob('generation-*/criteria.json'))]
 path=OUT/'gap-inspection'/f'{key[0]}--{key[1]}--rep-{key[2]:03d}.json';write(path,result)
 return {'arm':key[0],'task_id':key[1],'replicate':key[2],'selection_reasons':sorted(reasons),**deltas,'packet_path':str(path),'packet_sha256':sha(path),'packet_bytes':path.stat().st_size}


def main():
 assert os.environ.get('SLURM_JOB_ID') and read(RUN/'completion.json')['success']
 cases=list(csv.DictReader((PUBLIC/'case-differences-vs-static.csv').open()));tasks=list(csv.DictReader((PUBLIC/'task-gap-contributors.csv').open()))
 selected=defaultdict(set)
 for arm in ('full','user'):
  ts=[t for t in tasks if t['arm']==arm]
  for metric in ('W_minus_S','W_minus_A'):
   for t in sorted(ts,key=lambda t:(float(t['delta_'+metric]),t['task_id']))[:3]:
    for rep in (1,2,3):selected[arm,t['task_id'],rep].add('top_three_task_contributors_'+metric)
 for c in cases:
  if c['narrower_gap_with_substantial_A_loss']=='True':selected[c['arm'],c['task_id'],int(c['replicate'])].add('narrower_gap_with_delta_A_at_most_minus_5')
 frozen=read(OUT/'frozen-cohorts.json');fresh=read(OUT/'candidate-rows.json');old=defaultdict(list);new=defaultdict(list);diff={}
 for arm in ('full','user'):
  for r in frozen['static_'+arm]:old[arm,r['task_id'],r['replicate']].append(r)
 for r in fresh:new['user' if r['condition_id'].startswith('user') else 'full',r['task_id'],r['replicate']].append(r)
 for c in cases:diff[c['arm'],c['task_id'],int(c['replicate'])]={k:float(v) for k,v in c.items() if k.startswith('delta_')}
 items=[(k,reasons,old[k],new[k],diff[k]) for k,reasons in sorted(selected.items())]
 with ThreadPoolExecutor(max_workers=4) as pool:index=list(pool.map(packet,items))
 table('gap-inspection-index.csv',index);write(PUBLIC/'gap-inspection-index.json',index)
 print(json.dumps({'inspection_packets':len(index),'provider_calls':0,'selection':'descriptive task contributors and all flagged substantial quality losses; no endpoint exclusions'}),flush=True)

if __name__=='__main__':main()
