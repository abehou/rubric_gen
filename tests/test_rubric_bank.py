from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import rubric_gen.submission_revision.rubric_bank as bank_module
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankGeneration,
    RubricBankItem,
    RubricBankPolicy,
    RubricBankSchedule,
    RubricCriterionMapping,
    RubricLineage,
    identity_criterion_map,
    load_rubric_bank,
    parse_rubric_member_presentation,
    persist_rubric_bank,
    render_locked_rubric_member,
    validate_rubric_criterion_map,
)


def _rubric(
    name: str,
    *,
    maximum: int = 100,
    protocol: str | None = None,
) -> CompleteRubric:
    directives = ""
    if protocol is not None:
        directives = (
            f"Scoring protocol: {protocol}\n"
            f"Score normalization maximum: {maximum}\n\n"
        )
        levels = f"A={maximum} B=0"
        descriptions = "[A]: Fully satisfied.\n[B]: Not satisfied.\n"
    else:
        if maximum != 100:
            directives = f"Score normalization maximum: {maximum}\n\n"
        levels = f"A={maximum} B={maximum // 2} C=0"
        descriptions = (
            "[A]: Fully satisfied.\n"
            "[B]: Partly satisfied.\n"
            "[C]: Not satisfied.\n"
        )
    return CompleteRubric.from_content(
        f"RUBRIC: {name}\n\n"
        f"{directives}"
        f"Criterion 1: {name} outcome\n"
        f"Description: Evaluate {name}.\n"
        f"Levels: {levels}\n"
        f"{descriptions}"
    )


def _two_criterion_rubric(
    name: str,
    *,
    first_points: tuple[int, int, int] = (60, 30, 0),
    second_points: tuple[int, int, int] = (40, 20, 0),
) -> CompleteRubric:
    def levels(points: tuple[int, int, int]) -> str:
        return f"A={points[0]} B={points[1]} C={points[2]}"

    return CompleteRubric.from_content(
        f"RUBRIC: {name}\n\n"
        f"Criterion 1: {name} first\n"
        "Description: Evaluate the first requirement.\n"
        f"Levels: {levels(first_points)}\n"
        "[A]: Fully satisfied.\n[B]: Partly satisfied.\n[C]: Not satisfied.\n\n"
        f"Criterion 2: {name} second\n"
        "Description: Evaluate the second requirement.\n"
        f"Levels: {levels(second_points)}\n"
        "[A]: Fully satisfied.\n[B]: Partly satisfied.\n[C]: Not satisfied.\n"
    )


def _large_rubric(name: str, criterion_count: int = 100) -> CompleteRubric:
    criteria = []
    for index in range(1, criterion_count + 1):
        top = 1 if index <= 100 else 0
        middle = 0 if top else -1
        bottom = -1 if top else -2
        criteria.append(
            f"Criterion {index}: {name} requirement {index}\n"
            f"Description: Evaluate requirement {index}.\n"
            f"Levels: A={top} B={middle} C={bottom}\n"
            "[A]: Fully satisfied.\n[B]: Partly satisfied.\n[C]: Not satisfied.\n"
        )
    return CompleteRubric.from_content(f"RUBRIC: {name}\n\n" + "\n".join(criteria))


def _item(
    rubric: CompleteRubric,
    weight: float,
    lineage: RubricLineage = RubricLineage.NEW,
    prior: CompleteRubric | None = None,
    criterion_map: tuple[RubricCriterionMapping, ...] | None = None,
) -> RubricBankItem:
    return RubricBankItem(
        rubric=rubric,
        weight=weight,
        lineage=lineage,
        criterion_map=(
            criterion_map
            if criterion_map is not None
            else (RubricCriterionMapping("criterion_1", "criterion_1"),)
        ),
        prior_content_sha256=prior.content_sha256 if prior is not None else None,
    )


def _initial_bank(rubric: CompleteRubric | None = None) -> RubricBank:
    anchor = rubric or _rubric("initial")
    return RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=anchor,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(
            _item(
                anchor,
                1.0,
                criterion_map=identity_criterion_map(anchor),
            ),
        ),
    )


def _replacement_bank(
    prior: RubricBank,
    rubrics: tuple[CompleteRubric, ...],
    *,
    source_boundary: int | None = None,
    generation_round: int = 1,
    lineages: tuple[RubricLineage, ...] | None = None,
    prior_rubrics: tuple[CompleteRubric | None, ...] | None = None,
    anchor: CompleteRubric | None = None,
    weights: tuple[float, ...] | None = None,
) -> RubricBank:
    next_anchor = anchor or prior.specification_anchor
    anchor_lineage = (
        RubricLineage.RETAINED
        if next_anchor == prior.specification_anchor
        else RubricLineage.REFINED
    )
    lineages = lineages or tuple(RubricLineage.NEW for _ in rubrics)
    prior_rubrics = prior_rubrics or tuple(None for _ in rubrics)
    weights = weights or tuple(1 / len(rubrics) for _ in rubrics)
    if not (
        len(rubrics) == len(lineages) == len(prior_rubrics) == len(weights)
    ):
        raise ValueError("test replacement inputs must have equal lengths")
    prior_items = {
        item.rubric.content_sha256: item for item in prior.items
    }
    proposed: list[RubricBankItem] = []
    criterion_ids = [
        mapping.anchor_criterion_id for mapping in identity_criterion_map(next_anchor)
    ]
    for source, lineage, prior_rubric, weight in zip(
        rubrics,
        lineages,
        prior_rubrics,
        weights,
        strict=True,
    ):
        if lineage is RubricLineage.RETAINED:
            assert prior_rubric is not None
            prior_item = prior_items[prior_rubric.content_sha256]
            proposed.append(RubricBankItem(
                rubric=prior_item.rubric,
                weight=weight,
                lineage=lineage,
                criterion_map=prior_item.criterion_map,
                prior_content_sha256=prior_item.rubric.content_sha256,
                presentation=prior_item.presentation,
            ))
            continue
        label = source.content.splitlines()[0].removeprefix("RUBRIC: ")
        presentation = parse_rubric_member_presentation({
            "title": f"{label} presentation",
            "overview": f"Inspect the full anchor through {label} evidence.",
            "criteria": [{
                "anchor_criterion_id": criterion_id,
                "heading": f"{label} {criterion_id}",
                "lens": f"Inspect concrete {label} evidence.",
            } for criterion_id in criterion_ids],
        })
        rendered, criterion_map = render_locked_rubric_member(
            next_anchor,
            presentation,
        )
        proposed.append(RubricBankItem(
            rubric=rendered,
            weight=weight,
            lineage=lineage,
            criterion_map=criterion_map,
            prior_content_sha256=(
                prior_rubric.content_sha256 if prior_rubric is not None else None
            ),
            presentation=presentation,
        ))
    return RubricBank(
        generation_round=generation_round,
        source_boundary=source_boundary,
        specification_anchor=next_anchor,
        specification_anchor_lineage=anchor_lineage,
        prior_specification_anchor_sha256=(
            prior.specification_anchor.content_sha256
        ),
        items=tuple(sorted(
            proposed,
            key=lambda item: item.rubric.content_sha256,
        )),
    )


def test_complete_rubric_validates_hash_and_current_grammar() -> None:
    rubric = _rubric("valid")
    assert len(rubric.content_sha256) == 64

    with pytest.raises(ValueError, match="does not match"):
        CompleteRubric(rubric.content, "0" * 64)
    with pytest.raises(ValueError, match="structurally complete"):
        CompleteRubric.from_content(
            "Criterion 1: Fragment\nLevels: A=100 B=50 C=0\n"
        )
    with pytest.raises(ValueError, match="contiguous"):
        CompleteRubric.from_content(
            "Criterion 2: Gap\nLevels: A=100 B=50 C=0\n"
            "[A]: Full.\n[B]: Partial.\n[C]: None.\n"
        )


def test_complete_rubric_accepts_a_zero_maximum_penalty_criterion() -> None:
    rubric = CompleteRubric.from_content(
        "RUBRIC: Quality with source penalty\n\n"
        "Criterion 1: Quality\nDescription: Evaluate task quality.\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Fully correct.\n[B]: Partly correct.\n[C]: Incorrect.\n\n"
        "Criterion 2: Source reliability\n"
        "Description: Penalize unsupported claims.\n"
        "Levels: A=0 B=-5 C=-10\n"
        "[A]: All claims are supported.\n"
        "[B]: One claim has weak support.\n"
        "[C]: One claim is fabricated.\n"
    )
    assert "Levels: A=0 B=-5 C=-10" in rubric.content


def test_initial_bank_is_one_anchor_member_with_identity_map() -> None:
    bank = _initial_bank()
    assert bank.items[0].rubric == bank.specification_anchor
    assert bank.items[0].criterion_map == identity_criterion_map(
        bank.specification_anchor
    )
    with pytest.raises(ValueError, match="1 to 1"):
        RubricBank(
            generation_round=0,
            source_boundary=None,
            specification_anchor=bank.specification_anchor,
            specification_anchor_lineage=RubricLineage.NEW,
            prior_specification_anchor_sha256=None,
            items=(
                _item(
                    bank.specification_anchor,
                    0.5,
                    criterion_map=identity_criterion_map(
                        bank.specification_anchor
                    ),
                ),
                _item(_rubric("extra"), 0.5),
            ),
        )


def test_criterion_map_is_bijective_and_preserves_exact_point_vectors() -> None:
    anchor = _two_criterion_rubric("anchor")
    member = _two_criterion_rubric("member")
    valid_map = (
        RubricCriterionMapping("criterion_1", "criterion_1"),
        RubricCriterionMapping("criterion_2", "criterion_2"),
    )
    validate_rubric_criterion_map(anchor, member, valid_map)

    with pytest.raises(ValueError, match="exact member criterion order"):
        validate_rubric_criterion_map(
            anchor,
            member,
            (
                RubricCriterionMapping("criterion_1", "criterion_1"),
                RubricCriterionMapping("criterion_2", "criterion_1"),
            ),
        )
    skewed = _two_criterion_rubric(
        "skewed",
        first_points=(99, 50, 0),
        second_points=(1, 0, -1),
    )
    with pytest.raises(ValueError, match="point vector exactly"):
        validate_rubric_criterion_map(anchor, skewed, valid_map)


def test_current_bank_format_requires_one_member() -> None:
    prior = _initial_bank()
    single = _replacement_bank(prior, (_rubric("one"),))
    assert single.rubric_count == 1
    with pytest.raises(ValueError, match="1 to 1"):
        _replacement_bank(
            prior,
            (_rubric("a"), _rubric("b")),
        )
    RubricBankSchedule(
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        (RubricBankGeneration(prior, 0), RubricBankGeneration(single, 1)),
    )


@pytest.mark.parametrize(
    "weight", [0.0, -0.1, math.inf, -math.inf, math.nan, True]
)
def test_bank_rejects_nonpositive_or_nonfinite_weights(weight: float) -> None:
    with pytest.raises(ValueError, match="weight"):
        _item(_rubric("bad weight"), weight)


def test_bank_requires_unit_weight_and_is_immutable() -> None:
    prior = _initial_bank()
    bank = _replacement_bank(prior, (_rubric("member"),))
    with pytest.raises(ValueError, match="sole rubric member"):
        _replacement_bank(
            prior,
            (_rubric("wrong weight"),),
            weights=(0.5,),
        )
    assert bank.inverse_weight_concentration == 1.0
    with pytest.raises(FrozenInstanceError):
        bank.generation_round = 2  # type: ignore[misc]


def test_singleton_aggregate_preserves_noninteger_result() -> None:
    prior = _initial_bank()
    bank = _replacement_bank(prior, (_rubric("member"),))
    rubric_hash = bank.items[0].rubric.content_sha256
    assert bank.aggregate({rubric_hash: 60.5}) == 60.5
    assert bank.inverse_weight_concentration == 1.0
    with pytest.raises(ValueError, match="missing"):
        bank.aggregate({})


def test_singleton_lineage_allows_retain_refine_or_replace() -> None:
    initial = _initial_bank()
    prior = _replacement_bank(initial, (_rubric("prior"),))
    prior_rubric = prior.items[0].rubric
    retained = _replacement_bank(
        prior,
        (prior_rubric,),
        generation_round=2,
        lineages=(RubricLineage.RETAINED,),
        prior_rubrics=(prior_rubric,),
    )
    retained.validate_lineage(prior)
    refined = _replacement_bank(
        prior,
        (_rubric("refined"),),
        generation_round=2,
        lineages=(RubricLineage.REFINED,),
        prior_rubrics=(prior_rubric,),
    )
    refined.validate_lineage(prior)
    replacement = _replacement_bank(
        prior,
        (_rubric("new"),),
        generation_round=2,
    )
    replacement.validate_lineage(prior)


def test_refined_anchor_forbids_retained_member_and_scoring_contract_change() -> None:
    initial = _initial_bank()
    prior = _replacement_bank(initial, (_rubric("prior"),))
    refined_anchor = _rubric("refined anchor")
    with pytest.raises(ValueError, match="locked anchor rendering"):
        _replacement_bank(
            prior,
            (prior.items[0].rubric,),
            generation_round=2,
            anchor=refined_anchor,
            lineages=(RubricLineage.RETAINED,),
            prior_rubrics=(prior.items[0].rubric,),
        )

    changed_scale = _rubric("changed scale", maximum=50)
    changed = _replacement_bank(
        prior,
        (_rubric("scale", maximum=50),),
        generation_round=2,
        anchor=changed_scale,
    )
    with pytest.raises(ValueError, match="scoring contract"):
        changed.validate_lineage(prior)


def test_policy_schedule_separates_fixed_nonadaptive_and_adaptive() -> None:
    initial = _initial_bank()
    RubricBankSchedule(
        RubricBankPolicy.FIXED,
        (RubricBankGeneration(initial, 0),),
    )
    nonadaptive = _replacement_bank(
        initial,
        (_rubric("nonadaptive"),),
    )
    RubricBankSchedule(
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        (RubricBankGeneration(initial, 0), RubricBankGeneration(nonadaptive, 3)),
    )
    adaptive = _replacement_bank(
        initial,
        (_rubric("adaptive"),),
        source_boundary=0,
    )
    RubricBankSchedule(
        RubricBankPolicy.ADAPTIVE_REPLACEMENT,
        (RubricBankGeneration(initial, 0), RubricBankGeneration(adaptive, 3)),
    )
    with pytest.raises(ValueError, match="artifact boundary"):
        RubricBankSchedule(
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            (RubricBankGeneration(initial, 0), RubricBankGeneration(adaptive, 3)),
        )


def test_bank_persistence_is_exact_idempotent_and_tamper_evident(
    tmp_path: Path,
) -> None:
    generation = RubricBankGeneration(_initial_bank(), proposer_call_budget=3)
    manifest = persist_rubric_bank(
        tmp_path,
        generation,
        RubricBankPolicy.ADAPTIVE_REPLACEMENT,
    )
    payload = json.loads(manifest.read_text())
    assert payload["rubric_count"] == 1
    assert payload["inverse_weight_concentration"] == 1.0
    assert payload["specification_anchor"]["path"] == "specification-anchor.txt"
    assert payload["members"][0]["criterion_map"] == [{
        "anchor_criterion_id": "criterion_1",
        "member_criterion_id": "criterion_1",
    }]
    assert load_rubric_bank(
        tmp_path,
        0,
        expected_policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
    ) == generation
    assert persist_rubric_bank(
        tmp_path,
        generation,
        RubricBankPolicy.ADAPTIVE_REPLACEMENT,
    ) == manifest

    anchor_path = manifest.parent / "specification-anchor.txt"
    anchor_path.chmod(0o600)
    anchor_path.write_text(anchor_path.read_text() + "tamper\n")
    with pytest.raises(RuntimeError, match="invalid specification anchor"):
        load_rubric_bank(tmp_path, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("rubric_count", 3), ("inverse_weight_concentration", 99.0)],
)
def test_bank_load_rejects_tampered_derived_manifest_statistics(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    manifest = persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(_initial_bank(), proposer_call_budget=0),
        RubricBankPolicy.FIXED,
    )
    manifest.chmod(0o600)
    payload = json.loads(manifest.read_text())
    payload[field] = value
    manifest.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="derived statistics"):
        load_rubric_bank(tmp_path, 0, expected_policy=RubricBankPolicy.FIXED)


def test_bank_load_rejects_tampered_criterion_map(tmp_path: Path) -> None:
    manifest = persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(_initial_bank(), proposer_call_budget=0),
        RubricBankPolicy.FIXED,
    )
    manifest.chmod(0o600)
    payload = json.loads(manifest.read_text())
    payload["members"][0]["criterion_map"][0]["member_criterion_id"] = (
        "criterion_2"
    )
    manifest.write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="invalid values"):
        load_rubric_bank(tmp_path, 0)


def test_bank_persistence_never_publishes_a_failed_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation = RubricBankGeneration(_initial_bank(), proposer_call_budget=2)

    def fail_rename(_source: Path, _target: Path) -> None:
        raise OSError("injected rename failure")

    monkeypatch.setattr(bank_module.os, "rename", fail_rename)
    with pytest.raises(OSError, match="injected"):
        persist_rubric_bank(tmp_path, generation, RubricBankPolicy.FIXED)
    parent = tmp_path / "rubric-banks"
    assert not (parent / "bank-0000").exists()
    assert list(parent.iterdir()) == []


def test_replacement_persistence_requires_prior_and_exact_lineage(
    tmp_path: Path,
) -> None:
    prior = _initial_bank()
    replacement = _replacement_bank(
        prior,
        (_rubric("new"),),
    )
    with pytest.raises(RuntimeError, match="directory is missing"):
        persist_rubric_bank(
            tmp_path,
            RubricBankGeneration(replacement, 2),
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        )

    persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(prior, 0),
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )
    persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(replacement, 2),
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )
    assert load_rubric_bank(
        tmp_path,
        1,
        expected_policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    ).bank == replacement
