"""Read only the approved added-task inputs; no outcome or provider access."""
import json
from pathlib import Path
from make_configs import ROOT,BUNDLE,TASKS,RUN,SOURCE_POOL
from input_tools import check_task_inputs

def check(task):
    return check_task_inputs(task, root=ROOT, bundle=BUNDLE, run=RUN, source_pool=SOURCE_POOL)

if __name__=='__main__':
    rows=[check(task) for task in TASKS]
    out=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue6/input-inventory.json'
    out.write_text(json.dumps({'provider_calls':0,'tasks':rows,'new_assignments':60},indent=2)+'\n')
    print(json.dumps({'tasks_verified':len(rows),'assignments':sum(r['assignments'] for r in rows),'existing_seed_pools':sum(r['existing_new_seed_manifest'] for r in rows),'provider_calls':0}))
