"""Prepare the approved 30-task extension using the original Result20 runtime."""
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys

import yaml
from rubric_gen.runtime.process_environment import controlled_process_environment, install_controlled_process_environment

install_controlled_process_environment()
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'runs/healthbench-hard-result50-extension-20261006'
SOURCE = ROOT / 'runs/healthbench-hard-result20-semi-score-20260926/runtime-source'
QUOTAS = dict(global_health=6, context_seeking=5, hedging=5, health_data_tasks=5,
              communication=4, complex_responses=3, emergency_referrals=2)


def main():
    if OUTPUT.exists():
        raise FileExistsError(f'Prepared extension already exists: {OUTPUT}')
    selection = json.loads((HERE.parent / 'healthbench-hard-result100/selection.json').read_text())
    inventory = json.loads((HERE.parent / 'healthbench-hard-result100/manifest100.json').read_text())
    byid = {t['source_id']:t for t in inventory['tasks']}
    chosen = [t for t in selection['extension80'] if t['previously_run_dev3']]
    counts = Counter(t['theme'] for t in chosen)
    for theme, quota in QUOTAS.items():
        needed = quota - counts[theme]
        assert needed >= 0
        pool = [t for t in selection['extension80'] if t['theme']==theme and not t['previously_run_dev3']]
        assert len(pool) >= needed
        chosen.extend(pool[:needed])
    chosen.sort(key=lambda t:t['task_id'])
    assert len(chosen)==len({t['source_id'] for t in chosen})==30
    assert not {t['source_id'] for t in chosen}.intersection(t['source_id'] for t in inventory['tasks'][:20])
    assert Counter(t['theme'] for t in chosen)==Counter(QUOTAS)
    OUTPUT.mkdir(parents=True)
    shutil.copytree(SOURCE/'src', OUTPUT/'runtime-source/src',
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(HERE.parent/'healthbench-hard-result20/budget_proxy.py',OUTPUT/'budget_proxy.py')
    payload = yaml.safe_load((HERE.parent/'healthbench-hard-result20/local.yaml').read_text())
    remaining = yaml.safe_load((HERE.parent/'healthbench-hard-result20/remaining.yaml').read_text())
    payload['conditions'] += remaining['conditions']
    payload.pop('pretreatment_source',None)
    payload['tasks_dir'] = str(OUTPUT/'tasks')
    payload['tasks'] = [t['task_id'] for t in chosen]
    for t in chosen:
        shutil.copytree(Path(byid[t['source_id']]['task_dir']),OUTPUT/'tasks'/t['task_id'])
    for stage, folder in [('seed','seeds'),('paraphrase','paraphrases'),
                          ('revise','studies/{experiment_id}'),('detect','audits/{experiment_id}')]:
        payload['dag'][stage]['output_dir'] = str(OUTPUT/folder)
    (HERE/'extension.yaml').write_text(yaml.safe_dump(payload,sort_keys=False))
    shutil.copy2(HERE/'extension.yaml',OUTPUT/'experiment.yaml')
    runtime = json.loads((HERE.parent/'healthbench-hard-result20/runtime.json').read_text())
    (HERE/'runtime.json').write_text(json.dumps(runtime,indent=2)+'\n')
    manifest = dict(benchmark='healthbench-hard', retained20=inventory['tasks'][:20],
                    extension30=[{**byid[t['source_id']], 'task_dir':str(OUTPUT/'tasks'/t['task_id']),
                                  'theme':t['theme'], 'previously_run_dev3':t['previously_run_dev3']} for t in chosen],
                    extension_theme_counts=QUOTAS,
                    selection='Original prepared80 content ranking, proportionally stratified; retain six Dev3 source tasks; no outcome filtering')
    (HERE/'manifest50.json').write_text(json.dumps(manifest,indent=2)+'\n')
    env=controlled_process_environment()
    env.update(PYTHONPATH=str(OUTPUT/'runtime-source/src'),RUBRIC_GEN_PROJECT_ROOT=str(ROOT))
    check='''
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.benchmarks.answer_only.contract import HEALTHBENCH_HARD
from pathlib import Path
import sys
e=load_experiment(Path(sys.argv[1]))
assert len(e.assignments)==720 and len(e.task_ids)==30
assert e.protocol['min_revisions']==e.protocol['max_revisions']==3
assert len(e.payload['conditions'])==8
for task in e.task_ids: HEALTHBENCH_HARD.validate_task(e.tasks_dir/task)
print(e.experiment_id, '720 assignments, native validation passed, zero provider calls')
'''
    result=subprocess.run([sys.executable,'-c',check,str(HERE/'extension.yaml')],cwd=ROOT,env=env,
                          check=True,capture_output=True,text=True)
    print(result.stdout,flush=True)
    record=dict(source_runtime=str(SOURCE), scientific_settings='Original Result20, all eight conditions',
                historical_dev3_reuse='Source questions included; trajectories regenerated because effort/prompt versions differ',
                git_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,env=env,text=True).strip(),
                assignments=720, models={'solver_W':'gpt-5.6-luna low','RTT':'gpt-5.6-luna high'},
                scope='seed/paraphrase/revise only; no detect', expected_usd=58.2, planning_range_usd=[50,80],
                budget_usd=100, expected_wall_hours=[10,14], extension_themes=QUOTAS)
    (OUTPUT/'preparation.json').write_text(json.dumps(record,indent=2)+'\n')
    (OUTPUT/'source.diff').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=ROOT,env=env))


if __name__=='__main__':
    main()
