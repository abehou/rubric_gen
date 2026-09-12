"""Native matched Full fixed/trace shards for the official ten-task addition."""
from copy import deepcopy
from pathlib import Path
import json
import yaml
ROOT=Path(__file__).resolve().parents[3]
BUNDLE=ROOT/'experiments/biomnibench-v21-to45/queue6'
MEMBERSHIP=json.loads((BUNDLE/'membership.json').read_text())
TASKS=tuple(MEMBERSHIP['additional10'])
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results30')
SOURCE_POOL=Path('/data/user_data/aydanh/rubric_gen/pools/paraphrases/biomnibench/confirmation-20260909/additional25')
if __name__=='__main__':
    base=yaml.safe_load((ROOT/'experiments/trace-attack-defense-v21/result20.yaml').read_text())
    for task in TASKS:
        d=deepcopy(base);d.pop('pretreatment_source')
        d['conditions']=[c for c in d['conditions'] if c['feedback_policy']=='full']
        d['execution_conditions']=[c['condition_id'] for c in d['conditions']]
        d['tasks']=[task]
        for stage,leaf in [('seed','inputs/seeds'),('paraphrase','inputs/paraphrases'),('revise','study/{experiment_id}'),('detect','audit/{experiment_id}')]:
            d['dag'][stage]['output_dir']=str(RUN/task/leaf)
        out=BUNDLE/'configs'/f'{task}.yaml';out.parent.mkdir(exist_ok=True)
        out.write_text(yaml.safe_dump(d,sort_keys=False))
    print(json.dumps({'native_task_shards':len(TASKS),'new_assignments':6*len(TASKS),'replicates':3}))
