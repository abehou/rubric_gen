import json
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment

ROOT=Path('/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2')
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')
for task in ('da-3-4','da-11-1','da-18-1'):
    p=ROOT/'experiments/trace-attack-defense-v2/dev2'/(task+'.yaml')
    e=load_experiment(p)
    root=RUN/'dev3/dev2'/task/'study'/e.experiment_id
    print(json.dumps({'task':task,'experiment_id':e.experiment_id,'study_root':str(root),
                      'study_exists':root.is_dir(),'ledger':str(root/'study.json'),
                      'ledger_exists':(root/'study.json').is_file(),
                      'pretreatment':str(root/'pretreatment-rubrics'),
                      'pretreatment_exists':(root/'pretreatment-rubrics').is_dir()},sort_keys=True),flush=True)
