"""Appendix-only ablations; mocked scientific verdicts test wiring, not accuracy."""
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision import trace_defense_delivery as delivery
from rubric_gen.submission_revision.feedback import FeedbackPolicy, ProjectedFeedback
from rubric_gen.submission_revision.trace_defense_registry import recipe, prompt_hashes
from test_user_delivery_v3 import _criterion, _generation

VERSIONS = ('attack_defense_v2.1_corrective_appendix', 'attack_defense_v2.1_no_appendix')
ROOT = Path(__file__).resolve().parents[1]


def setup(tmp_path, monkeypatch, points=0):
    generation = _generation((_criterion(),))
    generation.red_team_trace_version = 'attack_defense_v2.1'
    score = tmp_path/'score.json'
    score.write_text('{}')
    monkeypatch.setattr(delivery, '_validate_score_record', lambda *a: (None,None,None,{'criterion_1':20,'criterion_2':points}))
    args = dict(generation=generation, score_validation_path=score, root=tmp_path,
                submission_id='s000', instruction='Task', allow_generation=True)
    return ProjectedFeedback(20, {'decision':'revise','concerns':[]}, 'ordinary User feedback'), args


def test_legacy_message_and_receipt_bytes_equal(tmp_path, monkeypatch):
    projected,args = setup(tmp_path,monkeypatch,-5)
    old = dict(delivery.__dict__)
    exec(subprocess.check_output(['git','show','c866831:src/rubric_gen/submission_revision/trace_defense_delivery.py'],cwd=ROOT,text=True),old)
    old['_validate_score_record']=delivery._validate_score_record
    expected=old['append_reminder'](projected,**args)
    before=(tmp_path/'trace-defense-reminders/s000.json').read_bytes()
    assert delivery.append_reminder(projected,**args)==expected
    assert (tmp_path/'trace-defense-reminders/s000.json').read_bytes()==before


@pytest.mark.parametrize('mode,points,emitted',[
    ('corrective_only',-5,True),('corrective_only',0,False),('none',-5,False),('none',0,False)])
def test_same_selection_filters_only_block_and_resumes(tmp_path,monkeypatch,mode,points,emitted):
    projected,args=setup(tmp_path,monkeypatch,points)
    selection,skips=delivery.select_reminder(**{k:v for k,v in args.items() if k!='allow_generation'})
    result=delivery.append_reminder(projected,**args,delivery_mode=mode)
    record=json.loads((tmp_path/'trace-defense-reminders/s000.json').read_text())
    assert record['selection']==selection and record['skipped']==skips
    assert record['appendix_emitted'] is emitted
    assert record['appendix_suppressed'] is (not emitted)
    assert result.score==projected.score and result.payload==projected.payload
    if emitted:
        assert record['message_component']==delivery.CORRECTIVE.format(admitted_requirement=selection['requirement'])
        assert result.prompt==projected.prompt+'\n\n'+record['message_component']
    else:
        assert result.prompt==projected.prompt and record['message_component']==''
    # Resume is a replay, not another model draw or a selection-policy reset.
    args['allow_generation']=False
    before=(tmp_path/'trace-defense-reminders/s000.json').read_bytes()
    assert delivery.append_reminder(projected,**args,delivery_mode=mode)==result
    assert (tmp_path/'trace-defense-reminders/s000.json').read_bytes()==before
    with pytest.raises(RuntimeError,match='persisted trace reminder changed'):
        delivery.append_reminder(projected,**args,delivery_mode='legacy')


@pytest.mark.parametrize('mode',['corrective_only','none'])
def test_suppressed_selection_still_counts_in_legacy_history(tmp_path,monkeypatch,mode):
    projected,args=setup(tmp_path,monkeypatch)
    delivery.append_reminder(projected,**args,delivery_mode=mode)
    args['submission_id']='s001'
    delivery.append_reminder(projected,**args,delivery_mode=mode)
    second=json.loads((tmp_path/'trace-defense-reminders/s001.json').read_text())
    assert second['selection'] is None  # passing new rule is not selected twice
    assert second['appendix_emitted'] is False and second['appendix_suppressed'] is False
    monkeypatch.setattr(delivery,'_validate_score_record',lambda *a:(None,None,None,{'criterion_1':20,'criterion_2':-5}))
    args['submission_id']='s002'
    delivery.append_reminder(projected,**args,delivery_mode=mode)
    third=json.loads((tmp_path/'trace-defense-reminders/s002.json').read_text())
    assert third['selection']['previously_reminded'] is True
    assert third['selection']['corrective'] is True


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('policy',list(FeedbackPolicy))
def test_controller_full_isolation_and_user_only_appendix(tmp_path,monkeypatch,version,policy):
    from rubric_gen.submission_revision.controller_scoring import RevisionScorer
    projected,args=setup(tmp_path,monkeypatch)
    args['generation'].red_team_trace_version=version
    (tmp_path/'instruction.md').write_text('Task')
    scorer=SimpleNamespace(trace_defense_enabled=True,
        config=SimpleNamespace(red_team_trace_version=version,feedback_policy=policy),
        experiment_dir=tmp_path,task_dir=tmp_path,_ordinary_checkpoint_feedback=lambda **k:projected)
    actual=RevisionScorer.project_checkpoint_feedback(scorer,generation=args['generation'],
        artifacts=SimpleNamespace(score_validation_path=args['score_validation_path']),submission_id='s000',allow_generation=True)
    assert (actual.prompt==projected.prompt) is (policy is FeedbackPolicy.USER_SIMULATOR)
    scorer.trace_defense_enabled=False
    assert RevisionScorer.project_checkpoint_feedback(scorer)==projected


def test_native_learning_scoring_simulator_unchanged():
    for version in VERSIONS:
        assert recipe(version) is recipe('attack_defense_v2.1')
        assert prompt_hashes(version)==prompt_hashes('attack_defense_v2.1')
    for name in ('trace_defense_v21.py','trace_defense_v2_prompts.py','trace_defense_v2_schema.py',
                 'evolution_protocol.py','generation_scoring.py','user_simulator.py','feedback.py'):
        rel='src/rubric_gen/submission_revision/'+name
        assert (ROOT/rel).read_bytes()==subprocess.check_output(['git','show','c866831:'+rel],cwd=ROOT)

    rel='src/rubric_gen/submission_revision/trace_defense_v2_stage.py'
    stage=(ROOT/rel).read_text().replace("'attack_defense_v2.1_corrective_appendix', 'attack_defense_v2.1_no_appendix', 'attack_defense_v2.1_score_only_no_appendix', ", '')
    assert stage==subprocess.check_output(['git','show','c866831:'+rel],cwd=ROOT,text=True)


@pytest.mark.parametrize('version',VERSIONS)
@pytest.mark.parametrize('no_change',[False,True])
def test_native_controller_user_timing_validation_and_resume(tmp_path,monkeypatch,version,no_change):
    import test_trace_defense_v2 as integration
    import test_submission_revision as fixture
    from rubric_gen.submission_revision import models
    from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig,SimulatedUserFeedback,SimulatedUserGeneration
    original_config=fixture._config
    simulator_config=SimulatedUserConfig(model='gpt-simulated-user')
    monkeypatch.setattr(fixture,'_config',lambda *a,**k:replace(original_config(*a,**k),
        feedback_policy=FeedbackPolicy.USER_SIMULATOR,feedback_simulator=simulator_config))
    calls=[]
    def generate(config,request):
        calls.append(request)
        assert 'focused_dynamic_check' not in request.evidence
        return SimulatedUserGeneration(text=json.dumps({'decision':'revise','concerns':[
            {'category':'evidence_traceability','feedback':'Verify the current result.'}]}),
            provider='openai',requested_model=config.model,effective_model=config.model,
            response_id=str(len(calls)),request_parameters={'max_output_tokens':config.max_output_tokens})
    original_dependencies=models.RevisionDependencies
    simulator=SimulatedUserFeedback(simulator_config,generator=generate)
    monkeypatch.setattr(models,'RevisionDependencies',lambda **kwargs:original_dependencies(**kwargs,feedback_simulator=simulator))
    monkeypatch.setattr(integration,'VERSION',version)
    integration.test_v2_controller_timing_terminal_and_recovery(tmp_path,monkeypatch,no_change)
    assert len(calls)==(2 if no_change else 3)
