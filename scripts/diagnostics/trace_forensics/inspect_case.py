"""Bounded read-only summaries for manual forensic review."""
import argparse
import json
from collect import OUT,read

p=argparse.ArgumentParser();p.add_argument('case');p.add_argument('--mode',choices=['proposals','feedback','manifest','pairs'],default='proposals');p.add_argument('--generation',type=int);p.add_argument('--chars',type=int,default=1400)
a=p.parse_args();c=read(OUT/'cases'/f'{a.case}.json')
if a.mode=='manifest':print(json.dumps(c['manifest'],indent=2))
elif a.mode=='proposals':
    for x in c['proposals']:
        if a.generation is not None and x['generation']!=a.generation:continue
        print(json.dumps({k:x[k] for k in ['generation','criterion_id','title','requirement','accepted','rejection_reason','provenance_pair_ids']},ensure_ascii=False))
elif a.mode=='feedback':
    for x in c['checkpoints']:
        if a.generation is not None and x['generation']!=a.generation:continue
        print('GEN',x['generation'],'NEXT TURN',x['solver_turn'],'PENALTY',x['penalty'])
        print(json.dumps(x['feedback'],ensure_ascii=False)[:a.chars])
        for cid,v in x['learned_levels'].items():print(cid,v['title'],v['level'],v['points'],v['reason'][:350])
elif a.mode=='pairs':
    for x in c['proposals']:
        if a.generation is not None and x['generation']!=a.generation:continue
        print(x['generation'],x['criterion_id'],x['title'],x['rejection_reason'])
        for pair in x['cited_pairs']:print(json.dumps(pair,ensure_ascii=False)[:a.chars])
