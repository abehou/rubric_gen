"""Exercise the real dispatcher with fake child processes, never providers."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts/babel'
    monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location('babel_test_launch',scripts/'launch.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module,'check_shared_mount',lambda:dict(filesystem='nfs4',server_locking=True))
    monkeypatch.setattr(module,'verify_smoke_outputs',lambda:dict(assignment_count=6))
    local=tmp_path/'scripts/babel';local.mkdir(parents=True)
    for name in ('launch.py','dev3.sbatch'):(local/name).write_text('frozen\n')
    monkeypatch.setattr(module,'__file__',str(local/'launch.py'))
    diagnostics=tmp_path/'scripts/diagnostics';diagnostics.mkdir()
    for name in ('check_audit_coverage.py','artifact_locations.py'):(diagnostics/name).write_text('frozen')
    (tmp_path/'src').mkdir();(tmp_path/'src/runtime.py').write_text('original\n')
    (tmp_path/'config').mkdir();(tmp_path/'config/runtime.json').write_text('{}')
    (tmp_path/'uv.lock').write_text('frozen\n')
    (tmp_path/'pyproject.toml').write_text('frozen\n')
    pool=tmp_path/'pool';pool.mkdir();(pool/'manifest.json').write_text('{}')
    (pool/'tasks/da-3-4/variant-000.failures').mkdir(parents=True)
    config=tmp_path/'dev3.yaml';config.write_text('fixed scientific config\n')
    exp=SimpleNamespace(path=config,task_ids=['da-3-4'],replicates=0,experiment_id='fixed',dag={'paraphrase':{'output_dir':str(pool)},'revise':{'output_dir':str(tmp_path/'study')}})
    monkeypatch.setattr(module,'configurations',lambda mode:[exp])
    validated=[];monkeypatch.setattr(module,'validate_inputs',lambda exps:validated.extend(exps))
    monkeypatch.setattr(module,'dotenv_values',lambda p:{'OPENAI_API_KEY':'secret-openai','ANTHROPIC_API_KEY':'secret-anthropic'})
    monkeypatch.setattr(module.subprocess,'check_output',lambda command,**kwargs:'test-commit' if kwargs.get('text') else b'')
    commands=[]
    class Child:
        pid=123456
        def __init__(self,command,**kwargs):commands.append(command)
        def wait(self):return 0
    monkeypatch.setattr(module.subprocess,'Popen',Child)
    monkeypatch.setattr(module,'Monitor',lambda *a:SimpleNamespace(sample=lambda:{}))
    monkeypatch.setenv('SLURM_JOB_ID','test-job')
    monkeypatch.setenv('OPENAI_API_KEY','');monkeypatch.setenv('ANTHROPIC_API_KEY','')
    monkeypatch.setattr(module.time,'sleep',lambda _:None)
    return module,commands,validated


def test_launcher_requires_allocation(launcher,monkeypatch):
    module,commands,_=launcher
    monkeypatch.delenv('SLURM_JOB_ID');monkeypatch.setattr(sys,'argv',['launch.py','smoke'])
    with pytest.raises(RuntimeError,match='Slurm allocation'):module.main()
    assert not commands


def test_full_requires_smoke_and_resume_rejects_source_drift(launcher,monkeypatch):
    module,commands,validated=launcher
    monkeypatch.setattr(sys,'argv',['launch.py','full'])
    with pytest.raises(RuntimeError,match='completed scientific smoke'):module.main()
    assert not commands
    monkeypatch.setattr(sys,'argv',['launch.py','smoke'])
    assert module.main()==0
    assert [c[1] for c in commands]==['revise','detect']
    assert [c[c.index('--max-concurrency')+1] for c in commands]==['8','8']
    assert all('--resume' in c for c in commands)
    monkeypatch.setattr(sys,'argv',['launch.py','full'])
    assert module.main()==0
    assert all(c[c.index('--max-concurrency')+1]=='8' for c in commands[2:])
    receipts=list(module.ROOT.glob('runs/**/launch.json'))
    assert receipts and validated
    assert 'secret-' not in ''.join(p.read_text() for p in receipts)
    (module.ROOT/'src/runtime.py').write_text('changed\n')
    with pytest.raises(RuntimeError,match='smoke source'):module.main()
    monkeypatch.setattr(sys,'argv',['launch.py','smoke'])
    with pytest.raises(RuntimeError,match='resume source/config identity changed'):module.main()
    assert len(commands)==4


def test_monitor_excludes_existing_completions_and_records_operational_metrics(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts/babel'
    monkeypatch.syspath_prepend(str(scripts))
    from monitor import Monitor
    from rubric_gen.runtime.capacity import emit, policy
    monkeypatch.setenv('SLURM_JOB_ID','monitor-test')
    study=tmp_path/'study';study.mkdir()
    ledger=study/'study.json';ledger.write_text(json.dumps({'records':[{'status':'completed'}]*2}))
    monitor=Monitor(policy()['coordination_dir'],tmp_path/'metrics.jsonl',[study])
    emit('operation_completed',operation='hosted-generation',request_key='opaque',elapsed_seconds=.5)
    first=monitor.sample()
    assert first['completed_assignments_per_hour']==0
    assert first['operation_p95_seconds']=={'hosted-generation':.5}
    ledger.write_text(json.dumps({'records':[{'status':'completed'}]*3}))
    last=monitor.sample()
    assert last['completed_assignments_per_hour']>0
    assert last['active_provider_slots']==0 and last['active_audit_studies']==0
    assert last['processes']>=1 and last['rss_kib']>0


@pytest.mark.parametrize('arguments',[['smoke','--workers','61'],['full','--recovery','--audit-workers','61']])
def test_launcher_rejects_out_of_budget_workers(launcher,monkeypatch,arguments):
    module,commands,_=launcher
    monkeypatch.setattr(sys,'argv',['launch.py',*arguments])
    with pytest.raises(SystemExit):module.main()
    assert not commands
