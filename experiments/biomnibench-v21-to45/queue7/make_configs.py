"""The precommitted final fifteen, with unchanged Full v2.1 scientific settings."""
from copy import deepcopy
from pathlib import Path
import json
import yaml
ROOT=Path(__file__).resolve().parents[3]
BUNDLE=ROOT/'experiments/biomnibench-v21-to45/queue7'
MEMBERSHIP=json.loads((ROOT/'experiments/biomnibench-v21-to45/queue6/membership.json').read_text())
TASKS=tuple(MEMBERSHIP['results45'][30:])
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results45-added15')
SOURCE_POOL=Path('/data/user_data/aydanh/rubric_gen/pools/paraphrases/biomnibench/confirmation-20260909/additional25')
if __name__=='__main__':
    assert len(TASKS)==15 and not set(TASKS)&set(MEMBERSHIP['results30'])
    assert not set(TASKS)&set(MEMBERSHIP['protected_dev3'])
    base=yaml.safe_load((ROOT/'experiments/biomnibench-v21-to45/queue6/configs/da-8-1.yaml').read_text())
    for task in TASKS:
        d=deepcopy(base);d['tasks']=[task]
        for stage,leaf in [('seed','inputs/seeds'),('paraphrase','inputs/paraphrases'),('revise','study/{experiment_id}'),('detect','audit/{experiment_id}')]:
            d['dag'][stage]['output_dir']=str(RUN/task/leaf)
        out=BUNDLE/'configs'/f'{task}.yaml';out.parent.mkdir(exist_ok=True)
        out.write_text(yaml.safe_dump(d,sort_keys=False))
    print(json.dumps({'native_task_shards':len(TASKS),'new_assignments':6*len(TASKS),'new_seed_blocks':3*len(TASKS)}))
