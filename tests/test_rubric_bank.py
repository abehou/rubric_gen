from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    ELICITED_REWARD_FRACTION,
    ElicitedCriterion,
    MAX_ELICITED_CRITERIA,
    RubricBank,
    RubricBankGeneration,
    RubricBankItem,
    RubricBankPolicy,
    RubricBankSchedule,
    RubricLineage,
    identity_criterion_map,
    load_rubric_bank,
    parse_elicited_criterion,
    persist_rubric_bank,
    render_augmented_rubric,
    validate_rubric_criterion_map,
)


def _rubric(*, paper: bool = False) -> CompleteRubric:
    if paper:
        return CompleteRubric.from_content(
            "Paper rubric.\n"
            "Scoring protocol: paperbench-code-dev\n"
            "Score normalization maximum: 100\n\n"
            "Criterion 1: Implement the loader\n"
            "Description: Implement every loader requirement.\n"
            "Levels: A=60 B=0\n"
            "[A]: Complete and correct.\n"
            "[B]: Missing or incorrect.\n\n"
            "Criterion 2: Implement the trainer\n"
            "Description: Implement every trainer requirement.\n"
            "Levels: A=40 B=0\n"
            "[A]: Complete and correct.\n"
            "[B]: Missing or incorrect.\n"
        )
    return CompleteRubric.from_content(
        "RUBRIC: Scientific task\n\n"
        "Criterion 1: Correct result\n"
        "Description: Produce the correct result.\n"
        "Levels: A=60 B=30 C=0\n"
        "[A]: Complete and correct.\n"
        "[B]: Partly correct.\n"
        "[C]: Missing or incorrect.\n\n"
        "Criterion 2: Reproducible evidence\n"
        "Description: Save reproducible evidence.\n"
        "Levels: A=40 B=20 C=0\n"
        "[A]: Complete and reproducible.\n"
        "[B]: Partly reproducible.\n"
        "[C]: Missing or unusable.\n"
    )


def _criterion(
    title: str = "Robustness check",
    *,
    paper: bool = False,
    generation: int = 1,
) -> ElicitedCriterion:
    levels = (
        (("A", "Complete and correct."), ("B", "Missing or incorrect."))
        if paper
        else (
            ("A", "Complete and correct."),
            ("B", "Partly correct."),
            ("C", "Missing or incorrect."),
        )
    )
    return ElicitedCriterion.create(
        title=title,
        requirement="Test the solution under a task-relevant perturbation.",
        level_descriptions=levels,
        support_pair_ids=("pair_1", "pair_3"),
        source_generation=generation,
    )


def _initial_bank(rubric: CompleteRubric | None = None) -> RubricBank:
    original = rubric or _rubric()
    return RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=original,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric=original,
            weight=1.0,
            lineage=RubricLineage.NEW,
            criterion_map=identity_criterion_map(original),
        ),),
    )


def _next_bank(
    prior: RubricBank,
    criteria: tuple[ElicitedCriterion, ...],
    *,
    source_boundary: int | None = None,
) -> RubricBank:
    all_criteria = prior.items[0].elicited_criteria + criteria
    rubric, criterion_map = render_augmented_rubric(
        prior.specification_anchor,
        all_criteria,
    )
    return RubricBank(
        generation_round=prior.generation_round + 1,
        source_boundary=source_boundary,
        specification_anchor=prior.specification_anchor,
        specification_anchor_lineage=RubricLineage.RETAINED,
        prior_specification_anchor_sha256=(
            prior.specification_anchor.content_sha256
        ),
        items=(RubricBankItem(
            rubric=rubric,
            weight=1.0,
            lineage=(
                RubricLineage.RETAINED
                if rubric == prior.items[0].rubric
                else RubricLineage.REFINED
            ),
            prior_content_sha256=prior.items[0].rubric.content_sha256,
            criterion_map=criterion_map,
            elicited_criteria=all_criteria,
        ),),
    )


def test_complete_rubric_is_hashed_frozen_and_strict() -> None:
    rubric = _rubric()
    assert len(rubric.content_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        rubric.content = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="content_sha256"):
        CompleteRubric(rubric.content, "0" * 64)


def test_elicited_criterion_identity_is_content_derived_and_round_trips() -> None:
    criterion = _criterion()
    assert criterion.criterion_id.startswith("elicited_")
    assert parse_elicited_criterion(criterion.as_dict()) == criterion
    changed = dict(criterion.as_dict())
    changed["title"] = "Changed"
    with pytest.raises(ValueError, match="ID does not match"):
        parse_elicited_criterion(changed)


def test_elicited_criterion_requires_two_distinct_support_pairs() -> None:
    with pytest.raises(ValueError, match="two distinct"):
        ElicitedCriterion.create(
            title="A valid title",
            requirement="A valid general requirement.",
            level_descriptions=(("A", "Yes."), ("B", "No."), ("C", "Absent.")),
            support_pair_ids=("pair_1",),
            source_generation=1,
        )


def test_no_elicited_criterion_keeps_the_original_rubric_byte_exact() -> None:
    original = _rubric()
    rendered, criterion_map = render_augmented_rubric(original, ())
    assert rendered == original
    assert criterion_map == identity_criterion_map(original)


def test_program_reserves_exact_reward_mass_and_preserves_original_text() -> None:
    original = _rubric()
    criterion = _criterion()
    rendered, criterion_map = render_augmented_rubric(original, (criterion,))
    parsed = parse_autorubric_rubric(rendered.content)

    assert [item.levels[0].points for item in parsed.criteria] == [48, 32, 20]
    assert sum(item.levels[0].points for item in parsed.criteria[:2]) == 80
    assert parsed.criteria[2].levels[0].points == round(
        100 * ELICITED_REWARD_FRACTION
    )
    assert "Produce the correct result." in rendered.content
    assert "Save reproducible evidence." in rendered.content
    assert criterion.criterion_id in rendered.content
    assert len(criterion_map) == 2


def test_program_preserves_a_zero_maximum_penalty_criterion() -> None:
    original = CompleteRubric.from_content(
        _rubric().content
        + "\nCriterion 3: Source reliability\n"
        "Description: Ground claims in identifiable sources.\n"
        "Levels: A=0 B=-5 C=-10\n"
        "[A]: All claims are traceable.\n"
        "[B]: Some claims lack clear support.\n"
        "[C]: Claims rely on fabricated or missing sources.\n"
    )

    rendered, criterion_map = render_augmented_rubric(
        original,
        (_criterion(),),
    )
    parsed = parse_autorubric_rubric(rendered.content)

    assert [item.levels[0].points for item in parsed.criteria] == [48, 32, 0, 20]
    assert [level.points for level in parsed.criteria[2].levels] == [0, -5, -10]
    assert len(criterion_map) == 3


def test_paper_rubric_uses_the_same_bounded_augmentation() -> None:
    original = _rubric(paper=True)
    criterion = _criterion(paper=True)
    rendered, _ = render_augmented_rubric(original, (criterion,))
    parsed = parse_autorubric_rubric(rendered.content)
    assert [item.levels[0].points for item in parsed.criteria] == [48, 32, 20]
    assert all(
        [level.label for level in item.levels] == ["A", "B"]
        for item in parsed.criteria
    )


def test_render_rejects_wrong_level_contract_and_duplicate_titles() -> None:
    with pytest.raises(ValueError, match="scoring protocol"):
        render_augmented_rubric(_rubric(paper=True), (_criterion(),))
    duplicate = _criterion("Correct result")
    with pytest.raises(ValueError, match="duplicate criterion titles"):
        render_augmented_rubric(_rubric(), (duplicate,))


def test_bank_contains_exactly_one_unit_weight_rubric() -> None:
    initial = _initial_bank()
    assert initial.rubric_count == 1
    assert initial.items[0].weight == 1.0
    with pytest.raises(ValueError, match="1 to 1"):
        RubricBank(
            generation_round=0,
            source_boundary=None,
            specification_anchor=initial.specification_anchor,
            specification_anchor_lineage=RubricLineage.NEW,
            prior_specification_anchor_sha256=None,
            items=(),
        )


def test_original_rubric_cannot_change_after_generation_zero() -> None:
    initial = _initial_bank()
    changed = _rubric(paper=True)
    with pytest.raises(ValueError, match="original rubric"):
        RubricBank(
            generation_round=1,
            source_boundary=None,
            specification_anchor=changed,
            specification_anchor_lineage=RubricLineage.RETAINED,
            prior_specification_anchor_sha256=initial.specification_anchor.content_sha256,
            items=initial.items,
        )


def test_lineage_only_allows_cumulative_append_or_exact_retention() -> None:
    initial = _initial_bank()
    first = _next_bank(initial, (_criterion(),))
    first.validate_lineage(initial)
    retained = _next_bank(first, ())
    retained.validate_lineage(first)
    second = _next_bank(
        first,
        (_criterion("Calibration check", generation=2),),
    )
    second.validate_lineage(first)

    with pytest.raises(ValueError, match="deterministic augmentation"):
        RubricBank(
            generation_round=2,
            source_boundary=None,
            specification_anchor=first.specification_anchor,
            specification_anchor_lineage=RubricLineage.RETAINED,
            prior_specification_anchor_sha256=(
                first.specification_anchor.content_sha256
            ),
            items=(RubricBankItem(
                rubric=second.items[0].rubric,
                weight=1.0,
                lineage=RubricLineage.REFINED,
                prior_content_sha256=first.items[0].rubric.content_sha256,
                criterion_map=second.items[0].criterion_map,
                elicited_criteria=tuple(
                    reversed(second.items[0].elicited_criteria)
                ),
            ),),
        )


def test_criterion_capacity_is_fixed() -> None:
    criteria = tuple(
        _criterion(f"Check {index}")
        for index in range(MAX_ELICITED_CRITERIA + 1)
    )
    with pytest.raises(ValueError, match="invalid value"):
        render_augmented_rubric(_rubric(), criteria)


def test_offline_and_online_source_boundaries_are_strict() -> None:
    initial = _initial_bank()
    offline = _next_bank(initial, (_criterion(),))
    online = _next_bank(initial, (_criterion(),), source_boundary=1)
    RubricBankSchedule(
        RubricBankPolicy.OFFLINE_ELICITATION,
        (
            RubricBankGeneration(initial, 0),
            RubricBankGeneration(offline, 4),
        ),
    )
    RubricBankSchedule(
        RubricBankPolicy.ONLINE_ELICITATION,
        (
            RubricBankGeneration(initial, 0),
            RubricBankGeneration(online, 4),
        ),
    )
    with pytest.raises(ValueError, match="live artifact boundary"):
        RubricBankSchedule(
            RubricBankPolicy.OFFLINE_ELICITATION,
            (
                RubricBankGeneration(initial, 0),
                RubricBankGeneration(online, 4),
            ),
        )


@pytest.mark.parametrize(
    ("policy", "source_boundary"),
    [
        (RubricBankPolicy.OFFLINE_ELICITATION, None),
        (RubricBankPolicy.ONLINE_ELICITATION, 1),
    ],
)
def test_bank_manifest_round_trip_is_exact(
    tmp_path: Path,
    policy: RubricBankPolicy,
    source_boundary: int | None,
) -> None:
    initial = _initial_bank()
    next_bank = _next_bank(
        initial,
        (_criterion(),),
        source_boundary=source_boundary,
    )
    persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(initial, 0),
        policy,
    )
    expected = RubricBankGeneration(next_bank, 4)
    persist_rubric_bank(tmp_path, expected, policy)
    assert load_rubric_bank(tmp_path, 1, expected_policy=policy) == expected
    assert not any(
        path.stat().st_mode & 0o222
        for path in (tmp_path / "rubric-banks" / "bank-0001").rglob("*")
    )


def test_manifest_rejects_the_removed_presentation_schema(tmp_path: Path) -> None:
    initial = _initial_bank()
    persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(initial, 0),
        RubricBankPolicy.FIXED,
    )
    manifest_path = tmp_path / "rubric-banks" / "bank-0000" / "manifest.json"
    manifest_path.chmod(0o600)
    value = json.loads(manifest_path.read_text())
    member = value["members"][0]
    member["presentation"] = None
    member.pop("elicited_criteria")
    manifest_path.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="invalid member"):
        load_rubric_bank(
            tmp_path,
            0,
            expected_policy=RubricBankPolicy.FIXED,
        )


def test_validate_map_rejects_any_manual_rubric_change() -> None:
    original = _rubric()
    criterion = _criterion()
    rendered, mapping = render_augmented_rubric(original, (criterion,))
    changed = CompleteRubric.from_content(
        rendered.content.replace("Calibration", "Different")
        if "Calibration" in rendered.content
        else rendered.content.replace("Robustness", "Different")
    )
    with pytest.raises(ValueError, match="deterministic augmentation"):
        validate_rubric_criterion_map(
            original,
            changed,
            mapping,
            (criterion,),
        )
