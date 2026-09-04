from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from rubric_gen.submission_revision.autorubric import parse_autorubric_rubric
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    ElicitedCriterion,
    RubricGeneration,
    RubricPolicy,
    parse_elicited_criterion,
    render_augmented_rubric,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    persist_rubric_generation,
    rubric_generation_directory,
)


def _rubric() -> CompleteRubric:
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


def _criterion() -> ElicitedCriterion:
    return ElicitedCriterion.create(
        title="Robustness check",
        requirement="Test the result under a task-relevant perturbation.",
        levels=(
            ("A", 0, "The check passes."),
            ("B", -3, "The check is incomplete."),
            ("C", -8, "The check fails or is absent."),
        ),
        provenance_pair_ids=(
            "pair_0000000000000001",
            "pair_0000000000000003",
        ),
        source_generation=1,
    )


def _initial() -> RubricGeneration:
    return RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=_rubric(),
        elicited_criteria=(),
        proposer_call_budget=0,
    )


def _evolution_files() -> dict[str, str]:
    return {
        "artifact-history.json": "{}\n",
        "pairwise-assessment-rubric-free.json": "{}\n",
        "pairwise-assessment-active-rubric.json": "{}\n",
        "pairwise-assessment-development-rubric.json": "{}\n",
        "pairwise-comparisons.json": "{}\n",
        "criterion-proposal.json": "{}\n",
        "criterion-validation.json": "{}\n",
        "aggregate-margins.json": "{}\n",
        "evolution.json": "{}\n",
    }


def test_complete_rubric_is_hashed_frozen_and_strict() -> None:
    rubric = _rubric()
    assert len(rubric.content_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        rubric.content = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="content_sha256"):
        CompleteRubric(rubric.content, "0" * 64)


def test_elicited_criterion_identity_round_trips() -> None:
    criterion = _criterion()
    assert parse_elicited_criterion(criterion.as_dict()) == criterion
    changed = dict(criterion.as_dict())
    changed["title"] = "Changed"
    with pytest.raises(ValueError, match="ID does not match"):
        parse_elicited_criterion(changed)


def test_generation_contains_one_complete_active_rubric() -> None:
    initial = _initial()
    criterion = _criterion()
    evolved = RubricGeneration(
        generation_round=1,
        source_checkpoint=None,
        rubric=render_augmented_rubric(initial.rubric, (criterion,)),
        elicited_criteria=(criterion,),
        proposer_call_budget=6,
    )
    evolved.validate_successor(initial)
    parsed = parse_autorubric_rubric(evolved.rubric.content)
    assert len(parsed.criteria) == 3
    assert evolved.elicited_criteria == (criterion,)


def test_self_contained_generation_round_trip(tmp_path: Path) -> None:
    initial = _initial()
    persist_rubric_generation(tmp_path, initial, RubricPolicy.ONLINE_ELICITATION)
    criterion = _criterion()
    evolved = RubricGeneration(
        generation_round=1,
        source_checkpoint=None,
        rubric=render_augmented_rubric(initial.rubric, (criterion,)),
        elicited_criteria=(criterion,),
        proposer_call_budget=6,
    )
    manifest = persist_rubric_generation(
        tmp_path,
        evolved,
        RubricPolicy.ONLINE_ELICITATION,
        evolution_files=_evolution_files(),
    )
    assert manifest == rubric_generation_directory(tmp_path, 1) / "manifest.json"
    assert load_rubric_generation(
        tmp_path,
        1,
        expected_policy=RubricPolicy.ONLINE_ELICITATION,
    ) == evolved
    assert sorted(path.name for path in manifest.parent.iterdir()) == [
        "aggregate-margins.json",
        "artifact-history.json",
        "criteria.json",
        "criterion-proposal.json",
        "criterion-validation.json",
            "evolution.json",
            "manifest.json",
            "pairwise-assessment-active-rubric.json",
            "pairwise-assessment-development-rubric.json",
            "pairwise-assessment-rubric-free.json",
            "pairwise-comparisons.json",
        "rubric.txt",
    ]


def test_generation_loader_rejects_changed_rubric(tmp_path: Path) -> None:
    persist_rubric_generation(
        tmp_path,
        _initial(),
        RubricPolicy.FIXED,
    )
    path = rubric_generation_directory(tmp_path, 0) / "rubric.txt"
    path.write_text(path.read_text() + "changed\n")
    with pytest.raises(RuntimeError, match="hash changed"):
        load_rubric_generation(tmp_path, 0)
