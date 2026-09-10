"""Create a traceable, explicitly selected support-review sample from saved pairs."""
import difflib,re,json,argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collect import OUT,PUBLIC,read,write,key

def one(c):
    c=read(OUT/'cases'/f'{key(c)}.json')
    eligible=[p for p in c['proposals'] if p['generation']>=2 and p['rejection_reason']=='criterion_support_failed' and re.search('execution|claim|consisten|traceab|reproduc',p['title'],re.I)]
    if not eligible:return None
    p=eligible[0];h=read(Path(p['path'])/'artifact-history.json');art={x['artifact_id']:x for x in h['artifacts']}
    pairs=[]
    for pair in p['cited_pairs']:
        a,b=art[pair['preferred_artifact_id']],art[pair['rejected_artifact_id']]
        diff='\n'.join(difflib.unified_diff(a['content'].splitlines(),b['content'].splitlines(),fromfile='PREFERRED',tofile='REJECTED',n=3))
        pairs.append(dict(**pair,diff=diff,preferred_content=a['content'],rejected_content=b['content']))
    return dict(case=key(c),generation=p['generation'],criterion_id=p['criterion_id'],title=p['title'],requirement=p['requirement'],levels=p['levels'],pairs=pairs,path=p['path'],file_sha256s=p['file_sha256s'])

p=argparse.ArgumentParser();p.add_argument('--show',type=int);p.add_argument('--limit',type=int,default=4);p.add_argument('--chars',type=int,default=4000);a=p.parse_args()
if a.show is None:
    cs=read(PUBLIC/'cases.json');wanted={(c['task_id'],c['replicate']) for c in cs if c['policy']=='candidate' and c['setting']=='user' and any(r['direct']['full_trajectory']['decision']=='reward_hacking_detected' for r in c['rows'])}
    chosen=[c for c in cs if c['setting']=='user' and (c['task_id'],c['replicate']) in wanted]
    with ThreadPoolExecutor(max_workers=8) as pool:rows=[r for r in pool.map(one,chosen) if r]
    write(OUT/'support-review.json',rows)
    print([(i,r['case'],r['generation'],r['title'],len(r['pairs'])) for i,r in enumerate(rows)])
else:
    rows=read(OUT/'support-review.json')
    for i,r in list(enumerate(rows))[a.show:a.show+a.limit]:
        print('\nINDEX',i,r['case'],r['generation'],r['criterion_id'],r['title'],r['requirement'],r['levels'])
        for q in r['pairs']:
            print(q['pair_id'],q['preferred_level'],q['rejected_level']);print('QUALITY',q['quality_reason']);print('PREFERRED',q['preferred_reason']);print('REJECTED',q['rejected_reason']);print(q['diff'][:a.chars])
