"""Early sidecar admission must not be confused with shared offline criteria."""
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907/policy_exposure.py'
    spec=importlib.util.spec_from_file_location('policy_exposure_test',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize('policy,expected', [('red_team_trace',0),('red_team_trace_early',1)])
def test_initial_sidecar_admission_and_penalty_exclude_shared_pretreatment(tmp_path,policy,expected):
    m=module()
    def write(relative,value):
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value));return p
    state=write('state.json',{})
    for gr in (0,1):
        prefix=f'rubric-generations/generation-{gr:04d}'
        write(prefix+'/manifest.json',dict(generation_round=gr,policy=policy,generation_sha256=f'g{gr}',rubric_sha256=f'r{gr}'))
        write(prefix+'/criteria.json',[dict(criterion_id='criterion-test')] if gr else [])
    prefix='rubric-generations/generation-0001'
    write(prefix+'/evolution.json',dict(rubric_gap_count=1,rubric_free_preference_count=1,accepted_candidate_ids=['criterion-test']))
    write(prefix+'/criterion-proposal.json',dict(criteria=[{}]))
    write(prefix+'/criterion-validation.json',dict(validations=[dict(observable=True,nonredundant=True)]))
    write(prefix+'/aggregate-margins.json',dict(decisions=[dict(accepted=True)]))
    write(prefix+'/artifact-history.json',dict(pairs=[{}]))
    evaluation=write('judgments/s000/r1/evaluation.json',dict(criteria={'criterion_1':{'points':100},'criterion_2':{'points':-5}}))
    write('rubric-evaluations/s000.json',dict(generation_round=1,generation_sha256='g1',rubric_sha256='r1',elicited_penalty=-5,submission_id='s000',evaluation_sha256=m.digest(evaluation)))
    row=dict(state_path=str(state),state_sha256=m.digest(state),assignment_id='seed1',condition_id=policy,task_id='task')
    report=write('report.json',dict(rows=[dict(row,model='sol'),dict(row,model='opus')]))
    result=m.inspect_report(report)['conditions'][policy]
    assert result['assignments']==1
    assert result['assignments_with_online_admission']==expected
    assert result['assignments_with_online_penalty']==expected
    assert result['counts'].get('initial_sidecar_accepted',0)==expected
    assert result['counts']['accepted_retained_final']==expected
    assert result['counts']['negative_penalty_checkpoints']==1
    state.write_text('{"changed": true}')
    with pytest.raises(AssertionError):m.inspect_report(report)
