"""Provider-free structural tests for the v2.1 duplicate-title guard."""

from dataclasses import replace
from types import SimpleNamespace

from rubric_gen.submission_revision import evolution_protocol as protocol
from rubric_gen.submission_revision.rubric_generation import (
    ElicitedCriterion,
    RubricGeneration,
    RubricPolicy,
    render_augmented_rubric,
)
from rubric_gen.submission_revision.trace_defense_v21 import (
    _assert_final_title_invariant,
    _title_collision,
    normalize_criterion_title,
)
from test_rubric_evolution import _rubric


def _criterion(title, *, pair='pair_' + '1' * 16, source=1, requirement=None):
    return ElicitedCriterion.create(
        title=title,
        requirement=requirement or f'Check {title}.',
        levels=(('A', 0, 'Pass.'), ('B', -5, 'Moderate.'), ('C', -10, 'Material.')),
        provenance_pair_ids=(pair,),
        source_generation=source,
    )


def _generation(criteria=()):
    rubric = render_augmented_rubric(_rubric(), tuple(criteria))
    return RubricGeneration(1, None, rubric, tuple(criteria), 19)


def _candidate(title, replaces=(), *, requirement=None):
    return protocol.CriterionCandidate(
        _criterion(title, source=2, requirement=requirement), tuple(replaces)
    )


def test_base_title_collision_is_candidate_local_and_final_invariant_is_strict():
    base_title = 'Correct answer'
    prior = _generation()
    collision = _title_collision(_rubric(), prior, (), _candidate(base_title))
    assert collision['colliding_criterion_type'] == 'base'
    assert collision['colliding_criterion_id'] == 'criterion_1'
    assert collision['colliding_criterion_title'] == base_title
    assert normalize_criterion_title(base_title) == collision['colliding_normalized_title']
    # The host rejects before render; the final invariant remains a loud guard.
    try:
        _assert_final_title_invariant(_rubric(), (_candidate(base_title).criterion,))
    except RuntimeError as exc:
        assert 'final criterion-title invariant' in str(exc)
    else:
        raise AssertionError('the final invariant must reject a base-title collision')


def test_active_learned_title_requires_exact_replacement():
    old = _criterion('Learned relation')
    prior = _generation((old,))
    duplicate = _candidate('Learned relation')
    assert _title_collision(_rubric(), prior, (), duplicate)['colliding_criterion_id'] == old.criterion_id
    replacement = _candidate('Learned relation', (old.criterion_id,), requirement='Refined check.')
    assert _title_collision(_rubric(), prior, (), replacement) is None
    active = protocol.update_criteria(prior, (replacement,))
    _assert_final_title_invariant(_rubric(), active)


def test_case_and_whitespace_variants_collide():
    old = _criterion('Mixed   Case  Relation')
    prior = _generation((old,))
    candidate = _candidate('mixed case relation')
    collision = _title_collision(_rubric(), prior, (), candidate)
    assert collision['colliding_criterion_type'] == 'learned'
    assert collision['colliding_normalized_title'] == 'mixed case relation'


def test_accepted_candidate_reserves_title_but_failed_candidate_does_not():
    first = _candidate('New relation')
    second = _candidate('new   RELATION')
    prior = _generation()
    assert _title_collision(_rubric(), prior, (first,), second)['colliding_criterion_type'] == 'accepted_candidate'
    # A candidate that failed native admission is not in accepted and reserves nothing.
    assert _title_collision(_rubric(), prior, (), second) is None


def test_noncolliding_candidate_keeps_v2_rendered_bytes():
    candidate = _candidate('A genuinely distinct relation')
    prior = _generation()
    assert _title_collision(_rubric(), prior, (), candidate) is None
    rendered = render_augmented_rubric(_rubric(), (candidate.criterion,))
    _assert_final_title_invariant(_rubric(), (candidate.criterion,))
    assert rendered.content == render_augmented_rubric(_rubric(), (candidate.criterion,)).content
    assert rendered.content_sha256 == render_augmented_rubric(_rubric(), (candidate.criterion,)).content_sha256


def test_saved_result20_failure_records_reproduce_duplicate_title_reason():
    # These are the exact sealed candidate/current-title identities from the two
    # failed v2 assignments; no task-specific exception exists in production.
    cases = [
        {
            'candidate_id': 'elicited_866a79aaeb60326b',
            'title': 'Direct evidence for cross-level module replication',
            'existing_id': 'elicited_accc1ceaf159d0d1',
            'pair_id': 'pair_b6460b3c0bd0fc16',
        },
        {
            'candidate_id': 'elicited_3d0f731b9301da30',
            'title': 'Qualify operational gene-set construction',
            'existing_id': 'elicited_cf41a4b7deeb5bfb',
            'pair_id': 'pair_c0f15828017f018b',
        },
    ]
    for case in cases:
        old = SimpleNamespace(criterion_id=case['existing_id'], title=case['title'])
        prior = SimpleNamespace(elicited_criteria=(old,))
        candidate = SimpleNamespace(
            criterion=SimpleNamespace(criterion_id=case['candidate_id'], title=case['title']),
            replaces=(),
        )
        collision = _title_collision(_rubric(), prior, (), candidate)
        assert collision['colliding_criterion_id'] == case['existing_id']
        rejection = {
            'reason': 'duplicate_criterion_title',
            'candidate_id': candidate.criterion.criterion_id,
            'candidate_title': candidate.criterion.title,
            'normalized_title': normalize_criterion_title(candidate.criterion.title),
            **collision,
            'pair_id': case['pair_id'],
            'generation': 6,
            'replacement_ids': list(candidate.replaces),
        }
        assert rejection['reason'] == 'duplicate_criterion_title'
        assert rejection['replacement_ids'] == []
