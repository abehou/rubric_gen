"""Explicit eight-cell matrix; separate score-only appendix-off supplement."""
from copy import deepcopy
from pathlib import Path
import json
import yaml
ROOT=Path(__file__).resolve().parents[3]
BUNDLE=ROOT/'experiments/biomnibench-v21-to45/queue3'
TASKS=('da-3-4','da-11-1','da-18-1')
POLICIES=('full','semi','score_only','user_simulator')
CONDITIONS=[{'condition_id':f"{p.replace('_','-')}-{suffix}", 'feedback_policy':p,'rubric_policy':r}
            for p in POLICIES for suffix,r in [('static','fixed'),('red-team-trace','red_team_trace')]]
# Cell outputs have distinct ownership. Every native declaration has exactly
# eight conditions; execution selects one, never the generic twenty arms.
CELLS={f'{p}-{r}':f"{p.replace('_','-')}-{'static' if r=='fixed' else 'red-team-trace'}"
       for p in POLICIES for r in ('fixed','trace') if (p,r)!=('user_simulator','trace')}
CELLS['score_only-trace-no-appendix']='score-only-red-team-trace'
if __name__=='__main__':
    for cell,condition in CELLS.items():
        for task in TASKS:
            base=yaml.safe_load((ROOT/f'experiments/biomnibench-v21-to45/queue2/configs/R1/{task}.yaml').read_text())
            d=deepcopy(base);d['conditions']=CONDITIONS
            d['protocol']['red_team_trace_version']=('attack_defense_v2.1_score_only_no_appendix'
                if cell=='score_only-trace-no-appendix' else 'attack_defense_v2.1')
            d['execution_conditions']=[condition]
            run=f'/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/queue3/{cell}/{task}'
            d['dag']['revise']['output_dir']=run+'/study/{experiment_id}'
            d['dag']['detect']['output_dir']=run+'/audit/{experiment_id}'
            out=BUNDLE/f'configs/{cell}/{task}.yaml';out.parent.mkdir(parents=True,exist_ok=True)
            out.write_text(yaml.safe_dump(d,sort_keys=False))
    print(json.dumps({'main_cells':8,'main_reused':9,'main_new':63,'supplement_new':9,'configs':len(CELLS)*3}))
