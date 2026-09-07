from rubric_gen.submission_revision.prompts import PromptProfile, revision_guidance, initial_guidance


def test_reward_seeking_is_distinct_from_base_and_sabotage():
    assert revision_guidance(PromptProfile.BASE) is None
    guidance = revision_guidance('reward-seeking')
    assert 'maximize the evaluator reward' in guidance
    assert 'Do not modify task' in guidance
    assert 'covert sabotage' not in guidance
    assert 'material failure' not in guidance
    assert initial_guidance('reward-seeking') == guidance
    assert 'material sabotage must remain' in revision_guidance('adversarial')


def test_score_only_revision_adds_objective_without_changing_feedback():
    from rubric_gen.submission_revision.feedback import render_revision_prompt
    args = dict(policy='score_only', payload={'score':73.0}, task_instruction='Analyze the provided data.', first_revision=True)
    base = render_revision_prompt(**args, prompt_profile='base')
    stress = render_revision_prompt(**args, prompt_profile='reward-seeking')
    assert stress.startswith(base.rstrip())
    assert 'Rubric score: 73/100' in base and 'Rubric score: 73/100' in stress
    assert stress.count('maximize the evaluator reward') == 1
