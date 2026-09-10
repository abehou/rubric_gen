"""Resolve saved ordinal score rows to stable learned-criterion identities."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collect import OUT,PUBLIC,read,write,table


def enrich(path):
    c=read(path); generations={g['generation']:g for g in c['generations']}
    rows=[]
    for x in c['checkpoints']:
        g=generations.get(x['generation'],{}); active=g.get('active_criteria',[])
        composition=read(x['score_composition_path'])
        ep=Path(c['root'])/'judgments'/x['submission']/composition['rubric_sha256']/'evaluation.json'
        ev=read(ep); ec=ev['criteria']; base_count=len(ec)-len(active)
        mapped={}
        for i,criterion in enumerate(active,base_count+1):
            score=ec[f'criterion_{i}']
            mapped[criterion['criterion_id']]=dict(ordinal=f'criterion_{i}',**score,
                title=criterion['title'],requirement=criterion['requirement'],source_generation=criterion['source_generation'])
        assert sum(v['points'] for v in mapped.values())==x['penalty'],(path,x['submission'])
        x['learned_levels']=mapped
        for cid,v in mapped.items():
            rows.append(dict(policy=c['policy'],setting=c['setting'],task_id=c['task_id'],replicate=c['replicate'],
                submission=x['submission'],generation=x['generation'],solver_turn=x['solver_turn'],criterion_id=cid,
                **v,title_literal_in_prompt=v['title'].lower() in (x['prompt'] or '').lower(),
                feedback=x['feedback'],prompt_path=x['prompt_path'],prompt_sha256=x['prompt_sha256']))
    write(path,c)
    return rows


if __name__=='__main__':
    assert os.environ.get('SLURM_JOB_ID')
    paths=sorted((OUT/'cases').glob('*.json'))
    with ThreadPoolExecutor(max_workers=8) as pool:rows=[r for chunk in pool.map(enrich,paths) for r in chunk]
    table('criterion-scoring-delivery.csv',rows)
    print('Mapped learned criterion/checkpoint rows:',len(rows))
