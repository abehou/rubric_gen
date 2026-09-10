"""Exercise actual acceptance receipts and fail-closed source/config guards."""
import importlib.util
from pathlib import Path
import pytest
BUNDLE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('evidence_launcher',BUNDLE/'condition_launch.py')
launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)

def test_accepted_control_and_canonical_tasks():
    for task in ['da-3-4','da-11-1','da-18-1']:
        exp,receipt,commit=launcher.gate('control',task)
        assert len(exp.execution_assignments)==6
        assert commit.startswith('6498d78')

@pytest.mark.parametrize('arm,task',[('unknown','da-11-1'),('control','new-task')])
def test_scope_rejected(arm,task):
    with pytest.raises(ValueError,match='outside approved'):
        launcher.gate(arm,task)

def test_other_arm_source_rejected():
    with pytest.raises(RuntimeError,match='wrong source'):
        launcher.gate('evidence','da-11-1')

def test_modified_config_rejected(monkeypatch):
    original=launcher.sha
    monkeypatch.setattr(launcher,'sha',lambda p:'0'*64 if str(p).endswith('control-da-11-1.yaml') else original(p))
    with pytest.raises(RuntimeError,match='config changed'):
        launcher.gate('control','da-11-1')

def test_modified_source_rejected(monkeypatch):
    original=launcher.sha
    monkeypatch.setattr(launcher,'sha',lambda p:'0'*64 if '/src/' in str(p) else original(p))
    with pytest.raises(RuntimeError,match='source changed'):
        launcher.gate('control','da-11-1')
