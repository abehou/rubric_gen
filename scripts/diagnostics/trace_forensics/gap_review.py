"""Read final saved artifacts and existing quality rationales for largest gap movers."""
import argparse,json
from collect import *
from concurrent.futures import ThreadPoolExecutor
from traces import extract
p=argparse.ArgumentParser();p.add_argument('--show',type=int);p.add_argument('--limit',type=int,default=2);a=p.parse_args()
if a.show is None:
    wanted={('da-18-7',1),('da-19-6',2),('da-19-6',3),('da-14-3',1),('da-10-3',3),('da-15-1',3),('da-13-6',2),('da-13-6',1),('da-14-8',3),('da-15-7',2),('da-12-2',1)}
    def one(c):
        c=read(OUT/'cases'/f'{key(c)}.json');extract(c);r=c['rows'][0];w=Path(c['root'])/'submissions'/r['submission_id']/'workspace'
        files=[dict(path=str(w/name),sha256=sha(w/name),content=(w/name).read_text()) for name in ['answer.txt','trace.md']]
        quality=[dict(auditor=r['model'],path=r['quality_path'],sha256=sha(r['quality_path']),verdict=read(r['quality_path'])['verdict']) for r in c['rows']]
        return dict(case=key(c),files=files,quality=quality,admitted=[p for p in c['proposals'] if p['generation']>=2 and p['accepted']],feedback=[dict(generation=x['generation'],solver_turn=x['solver_turn'],feedback=x['feedback'],path=x['feedback_path'],sha256=x['feedback_sha256']) for x in c['checkpoints']],first_turn_snapshot_sha256=sha(Path(c['root'])/'submissions/s001/snapshot.json'))
    cs=[c for c in read(PUBLIC/'cases.json') if c['setting']=='user' and (c['task_id'],c['replicate']) in wanted]
    result=list(ThreadPoolExecutor(8).map(one,cs));write(OUT/'gap-review.json',result)
    # Keep detailed raw artifacts available in the published dossier, but trim repeat proposal internals.
    for r in result:r['admitted']=[{k:p[k] for k in ['generation','criterion_id','title','requirement','path']} for p in r['admitted']]
    write(PUBLIC/'gap-review-evidence.json',result)
    print([(i,r['case']) for i,r in enumerate(result)])
else:
    for i,r in list(enumerate(read(PUBLIC/'gap-review-evidence.json')))[a.show:a.show+a.limit]:
        print('\nINDEX',i,r['case']);print('ANSWER',r['files'][0]['content'][:2200]);print('QUALITY',r['quality']);print('ADMITTED',r['admitted'])
