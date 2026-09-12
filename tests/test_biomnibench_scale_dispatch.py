"""Scale preparation preserves native requests; mocked subprocesses do no science."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType,SimpleNamespace

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
Q6=ROOT/'experiments/biomnibench-v21-to45/queue6'
Q7=ROOT/'experiments/biomnibench-v21-to45/queue7'
spec=importlib.util.spec_from_file_location('scale_input_tools',Q6/'input_tools.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)

@pytest.mark.parametrize('lane',[0,1])
def test_seed_lane_same_native_commands_and_results_as_f017a3f(tmp_path,monkeypatch,lane):
    previous=subprocess.check_output(['git','show','f017a3f:experiments/biomnibench-v21-to45/queue6/seed_lane.py'],cwd=ROOT,text=True)
    tasks=('task-a','task-b','task-c');bundle=tmp_path/'bundle';run=tmp_path/'run'
    configs=ModuleType('make_configs');configs.ROOT=tmp_path;configs.BUNDLE=bundle;configs.TASKS=tasks;configs.RUN=run
    checks=ModuleType('check_inputs');checks.check=lambda t:{'task':t}
    monkeypatch.setitem(sys.modules,'make_configs',configs);monkeypatch.setitem(sys.modules,'check_inputs',checks)
    monkeypatch.setenv('SLURM_JOB_ID','test');monkeypatch.setenv('SLURM_CPUS_PER_TASK','4')
    monkeypatch.setenv('OPENAI_API_KEY','mock');monkeypatch.setenv('ANTHROPIC_API_KEY','mock')
    monkeypatch.setattr(sys,'argv',['seed_lane.py',str(lane)])
    monkeypatch.setattr(subprocess,'check_output',lambda *a,**k:'frozen-commit\n')
    from rubric_gen.runtime import capacity
    monkeypatch.setattr(capacity,'policy',lambda:{'aggregate_concurrency':60,'audit_studies':1})
    monkeypatch.setattr(helper,'policy',capacity.policy)
    commands=[]
    def invoke(command,**kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=1 if 'task-a.yaml' in command[-3] else 0)
    monkeypatch.setattr(subprocess,'run',invoke)
    with pytest.raises(SystemExit) as stopped:exec(previous,{'__name__':'__main__'})
    operation=run/'operations/seeds-test';old=json.loads((operation/'status.json').read_text());old_commands=list(commands)
    operation.rename(run/'operations/retained-test');commands.clear()
    code=helper.run_seed_lane(lane,root=tmp_path,bundle=bundle,tasks=tasks,run=run,check_task=checks.check)
    new=json.loads((operation/'status.json').read_text())
    assert code==stopped.value.code and commands==old_commands
    for d in (old,new):
        d.pop('started_at');d.pop('finished_at')
        for row in d['results']:row.pop('finished_at')
    assert new==old
    assert [x['task'] for x in new['results']]==list(tasks[lane::2])


def test_results45_membership_and_fixed_scientific_settings():
    membership=json.loads((Q6/'membership.json').read_text())
    configs=sorted((Q7/'configs').glob('*.yaml'))
    assert len(configs)==15
    expected=set(membership['results45'][30:]);assert len(expected)==15
    assert not expected&set(membership['results30'])
    assert not expected&set(membership['protected_dev3'])
    base=yaml.safe_load((Q6/'configs/da-8-1.yaml').read_text())
    assert {p.stem for p in configs}==expected
    for path in configs:
        raw=yaml.safe_load(path.read_text())
        assert raw['tasks']==[path.stem]
        assert raw['randomization']=={'replicates':3,'seed':20260820}
        for key,value in base.items():
            if key not in ('dag','tasks'):assert raw[key]==value,key
        for stage in ('seed','paraphrase','revise','detect'):
            assert raw['dag'][stage]['depends_on']==base['dag'][stage]['depends_on']
            assert '/results45-added15/'+path.stem+'/' in raw['dag'][stage]['output_dir']
