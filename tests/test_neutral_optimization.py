from rubric_gen.submission_revision.prompts import PromptProfile, initial_guidance, revision_guidance
from rubric_gen.submission_revision.feedback import render_revision_prompt


def test_neutral_profile_changes_only_revision_guidance():
    assert initial_guidance(PromptProfile.NEUTRAL_OPTIMIZATION) is None
    for first in [True, False]:
        for policy, payload in [('score_only', {'score':100}), ('user_simulator', {'decision':'accept','concerns':[]})]:
            args=dict(policy=policy,payload=payload,task_instruction='Analyze the table.',first_revision=first)
            base=render_revision_prompt(**args,prompt_profile='base')
            treatment=render_revision_prompt(**args,prompt_profile='neutral-optimization')
            assert treatment == base.rstrip()+'\n\n## Solver profile\n\n'+revision_guidance('neutral-optimization')+'\n'


def test_fixed_study_does_not_prepare_learned_rubrics():
    from types import SimpleNamespace
    from rubric_gen.submission_revision.study import StudyRunner
    study=object.__new__(StudyRunner)
    study.config=SimpleNamespace(max_concurrency=24)
    study.experiment=SimpleNamespace(condition=lambda _: {'rubric_policy':'fixed'})
    study._prepare_pretreatment_rubric=lambda *_: (_ for _ in ()).throw(AssertionError('Unexpected induction'))
    study._prepare_pretreatment_rubrics([SimpleNamespace(task_id='da-3-4',condition_id='full-static')])
