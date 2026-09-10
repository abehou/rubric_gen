"""Exercise actual acceptance receipts and fail-closed source/config guards."""
import importlib.util
from pathlib import Path
import pytest
BUNDLE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('evidence_launcher',BUNDLE/'condition_launch.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

def test_accepted_both_arms():
    for arm in ('static','trace'):
        exp,receipt,commit=launcher.gate(arm,'results20')
        assert len(exp.execution_assignments)==60 and len(exp.task_ids)==20
        assert commit.startswith('0fbe0bb')
        assert exp.outcome_audit['models']==['gpt-5.6-sol','claude-opus-5']

@pytest.mark.parametrize('arm,task',[('unknown','results20'),('static','new-task')])
def test_scope_rejected(arm,task):
    with pytest.raises(ValueError,match='outside approved'):
        launcher.gate(arm,task)

def test_wrong_source_rejected(monkeypatch):
    monkeypatch.setattr(launcher.subprocess,'check_output',lambda *a,**kw:'wrong')
    with pytest.raises(RuntimeError,match='wrong source'):
        launcher.gate('static','results20')

def test_modified_config_rejected(monkeypatch):
    original=launcher.sha
    monkeypatch.setattr(launcher,'sha',lambda p:'0'*64 if str(p).endswith('static-results20.yaml') else original(p))
    with pytest.raises(RuntimeError,match='config changed'):
        launcher.gate('static','results20')

def test_modified_source_rejected(monkeypatch):
    original=launcher.sha
    monkeypatch.setattr(launcher,'sha',lambda p:'0'*64 if '/src/' in str(p) else original(p))
    with pytest.raises(RuntimeError,match='source changed'):
        launcher.gate('static','results20')
