"""Native policy projections and explicitly scoped appendix-off routing."""
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from rubric_gen.submission_revision import trace_defense_delivery as delivery
from rubric_gen.submission_revision.feedback import FeedbackPolicy, ProjectedFeedback, render_revision_prompt
from rubric_gen.submission_revision.trace_defense_registry import recipe, prompt_hashes
from test_trace_appendix_ablations import setup
VERSION='attack_defense_v2.1_score_only_no_appendix'

@pytest.mark.parametrize('policy',list(FeedbackPolicy))
def test_score_only_switch_does_not_change_other_policies(policy):
    assert delivery.appendix_mode(VERSION,policy)==('none' if policy is FeedbackPolicy.SCORE_ONLY else 'legacy')
    assert delivery.appendix_mode('attack_defense_v2.1',policy)=='legacy'
    assert recipe(VERSION) is recipe('attack_defense_v2.1')
    assert prompt_hashes(VERSION)==prompt_hashes('attack_defense_v2.1')

@pytest.mark.parametrize('version',['attack_defense_v2.1',VERSION])
def test_native_score_only_feedback_and_appendix(tmp_path,monkeypatch,version):
    from rubric_gen.submission_revision.controller_scoring import RevisionScorer
    _,args=setup(tmp_path,monkeypatch,-5)
    args['generation'].red_team_trace_version=version
    (tmp_path/'instruction.md').write_text('Public task')
    prompt=render_revision_prompt(FeedbackPolicy.SCORE_ONLY,{'score':75},task_instruction='Public task',first_revision=True)
    projected=ProjectedFeedback(75,{'score':75},prompt)
    scorer=SimpleNamespace(trace_defense_enabled=True,
        config=SimpleNamespace(red_team_trace_version=version,feedback_policy=FeedbackPolicy.SCORE_ONLY),
        experiment_dir=tmp_path,task_dir=tmp_path,_ordinary_checkpoint_feedback=lambda **k:projected)
    result=RevisionScorer.project_checkpoint_feedback(scorer,generation=args['generation'],
        artifacts=SimpleNamespace(score_validation_path=args['score_validation_path']),submission_id='s000',allow_generation=True)
    record=json.loads((tmp_path/'trace-defense-reminders/s000.json').read_text())
    assert record['selection'] is not None
    assert result.payload=={'score':75}
    if version==VERSION:
        assert result.prompt==prompt
        assert not record['appendix_emitted'] and record['appendix_suppressed']
        assert 'Focused review check' not in result.prompt
    else:
        assert result.prompt==prompt+'\n\n'+record['message_component']
        assert 'Focused review check' in result.prompt
    text=result.prompt.split('<evaluation_feedback>')[1].split('</evaluation_feedback>')[0].strip()
    assert text=='Rubric score: 75/100'
    for private in ('judge_reason','criterion_','overall_reasoning'):
        assert private not in result.prompt

@pytest.mark.parametrize('policy',[FeedbackPolicy.SEMI,FeedbackPolicy.SCORE_ONLY])
@pytest.mark.parametrize('no_change',[False,True])
def test_native_trace_policy_timing_replay_and_resume(tmp_path,monkeypatch,policy,no_change):
    import test_trace_defense_v2 as integration
    import test_submission_revision as fixture
    original=fixture._config
    monkeypatch.setattr(fixture,'_config',lambda *a,**k:replace(original(*a,**k),feedback_policy=policy))
    monkeypatch.setattr(integration,'VERSION',VERSION if policy is FeedbackPolicy.SCORE_ONLY else 'attack_defense_v2.1')
    integration.test_v2_controller_timing_terminal_and_recovery(tmp_path,monkeypatch,no_change)
