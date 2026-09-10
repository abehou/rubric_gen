"""No-provider tests of the private overnight dispatcher."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest

@pytest.fixture
def condition_launcher(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'scripts/babel'))
    p=root/'investigation/babel-overnight-20260907/condition_launch.py'
    spec=importlib.util.spec_from_file_location('condition_test',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'CODE_ROOT',tmp_path)
    return m

def test_requires_real_smoke(condition_launcher):
    with pytest.raises(RuntimeError,match='successful real Babel'):condition_launcher.smoke_gate()

def test_wrong_checkout_rejected(condition_launcher):
    with pytest.raises(RuntimeError,match='wrong checkout'):condition_launcher.config_for('policy','da-3-4')

def test_fake_dispatch_resume_receipt_and_source_seal(condition_launcher,monkeypatch,tmp_path):
    m=condition_launcher
    for name in ('src/example.py','config/runtime.json','uv.lock','pyproject.toml','scripts/babel/monitor.py','scripts/babel/launch.py','scripts/diagnostics/check_audit_coverage.py','scripts/diagnostics/artifact_locations.py','condition_launch.py','condition.sbatch','pool/manifest.json','experiment.yaml'):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    monkeypatch.setattr(m,'__file__',str(tmp_path/'condition_launch.py'))
    monkeypatch.setattr(m,'check_shared_mount',lambda:{'server_locking':True})
    monkeypatch.setattr(m,'smoke_gate',lambda:None)
    exp=SimpleNamespace(path=tmp_path/'experiment.yaml',replicates=0,experiment_id='fixed',dag={'paraphrase':{'output_dir':str(tmp_path/'pool')},'revise':{'output_dir':str(tmp_path/'study')}})
    monkeypatch.setattr(m,'config_for',lambda *args:exp)
    monkeypatch.setattr(m,'validate_paraphrase_run',lambda *args:None)
    monkeypatch.setattr(m,'dotenv_values',lambda *args:{'OPENAI_API_KEY':'fake-secret-openai','ANTHROPIC_API_KEY':'fake-secret-anthropic'})
    monkeypatch.setenv('OPENAI_API_KEY','');monkeypatch.setenv('ANTHROPIC_API_KEY','');monkeypatch.setenv('SLURM_JOB_ID','fake-job')
    monkeypatch.setattr(m.subprocess,'check_output',lambda *args,**kw:'fake-commit' if kw.get('text') else b'')
    commands=[]
    class Child:
        pid=99999
        def __init__(self,command,**kwargs):commands.append(command)
        def poll(self):return 0
        def wait(self,**kwargs):return 0
    monkeypatch.setattr(m.subprocess,'Popen',Child)
    monkeypatch.setattr(m,'Monitor',lambda *args:SimpleNamespace(sample=lambda:{}))
    monkeypatch.setattr(sys,'argv',['condition_launch.py','concern1','da-3-4'])
    assert m.main()==0
    assert [c[1] for c in commands]==['revise','detect']
    assert all('--resume' in c and c[c.index('--max-concurrency')+1]=='60' for c in commands)
    monkeypatch.setattr(sys,'argv',['condition_launch.py','concern1','da-3-4','--recovery'])
    assert m.main()==0
    assert all(c[c.index('--max-concurrency')+1]=='2' for c in commands[2:])
    receipts=list(tmp_path.glob('runs/**/launch.json'))
    assert len(receipts)==2 and 'fake-secret' not in ''.join(p.read_text() for p in receipts)
    (tmp_path/'src/example.py').write_text('changed')
    with pytest.raises(RuntimeError,match='identity changed'):m.main()
    assert len(commands)==4
