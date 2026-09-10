"""Exposure counts must not duplicate assignments across auditors."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907/feedback_exposure.py'
    spec=importlib.util.spec_from_file_location('feedback_exposure_test',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def test_assignment_counts_and_changed_state_rejection(tmp_path):
    m=module();state=tmp_path/'state.json';state.write_text('{}')
    feedback=tmp_path/'feedback';feedback.mkdir()
    for i in range(2):
        (feedback/f's{i:03d}.json').write_text(json.dumps(dict(decision='revise',concerns=[dict(category='reproducibility',feedback='Check /app/output.')])) )
    row=dict(state_path=str(state),state_sha256=hashlib.sha256(state.read_bytes()).hexdigest(),analysis_condition='control/user',assignment_id='task-rep1',task_id='task',replicate=1,retained_revisions=1,attempted_turns=2,stop_reason='no_change')
    result=m.exposure([dict(row,model='a'),dict(row,model='b')])
    summary=result['conditions']['control/user']
    assert summary['assignments']==1 and summary['feedback_turns']==2
    assert summary['exact_repeated_concerns']==1 and summary['absolute_app_mentions']==2
    state.write_text('{"changed":true}')
    with pytest.raises(AssertionError,match='state changed'):m.exposure([row])
