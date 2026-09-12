"""Verify the official added15 source metadata without viewing new outcomes."""
import json
import sys
from make_configs import ROOT,BUNDLE,TASKS,RUN,SOURCE_POOL
sys.path.insert(0,str(ROOT/'experiments/biomnibench-v21-to45/queue6'))
from input_tools import check_task_inputs

def check(task):
    return check_task_inputs(task,root=ROOT,bundle=BUNDLE,run=RUN,source_pool=SOURCE_POOL)

if __name__=='__main__':
    rows=[check(t) for t in TASKS]
    out=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue7/input-inventory.json'
    out.write_text(json.dumps({'provider_calls':0,'tasks':rows,'new_assignments':90},indent=2)+'\n')
    print(json.dumps({'tasks_verified':len(rows),'new_assignments':90,'existing_seed_pools':sum(r['existing_new_seed_manifest'] for r in rows),'provider_calls':0}))
