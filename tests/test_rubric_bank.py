from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import rubric_gen.submission_revision.rubric_bank as bank_module
from rubric_gen.submission_revision.rubric_bank import (
    MAX_RUBRIC_BANK_ITEMS,
    CompleteRubric,
    RubricBank,
    RubricBankGeneration,
    RubricBankItem,
    RubricBankPolicy,
    RubricBankSchedule,
    RubricLineage,
    load_rubric_bank,
    persist_rubric_bank,
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


def _item(
    rubric: CompleteRubric,
    weight: float,
    lineage: RubricLineage = RubricLineage.NEW,
    prior: CompleteRubric | None = None,
) -> RubricBankItem:
    return RubricBankItem(
        rubric=rubric,
        weight=weight,
        lineage=lineage,
        prior_content_sha256=prior.content_sha256 if prior is not None else None,
    )


def _initial_bank() -> RubricBank:
    return RubricBank(
        0,
        None,
        (_item(_rubric("first"), 0.25), _item(_rubric("second"), 0.75)),
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
        "Criterion 1: Quality\n"
        "Description: Evaluate task quality.\n"
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


def test_bank_is_immutable_bounded_and_hash_is_order_independent() -> None:
    first = _rubric("a")
    second = _rubric("b")
    bank = RubricBank(0, None, (_item(first, 0.2), _item(second, 0.8)))
    reordered = RubricBank(0, None, (_item(second, 0.8), _item(first, 0.2)))

    assert bank.content_sha256 == reordered.content_sha256
    assert bank.rubric_count == 2
    with pytest.raises(FrozenInstanceError):
        bank.generation_round = 1  # type: ignore[misc]
    rubrics = tuple(_rubric(f"member {index}") for index in range(9))
    with pytest.raises(ValueError, match=f"1 to {MAX_RUBRIC_BANK_ITEMS}"):
        RubricBank(
            0,
            None,
            tuple(_item(rubric, 1 / 9) for rubric in rubrics),
        )


@pytest.mark.parametrize(
    "weight", [0.0, -0.1, math.inf, -math.inf, math.nan, True]
)
def test_bank_rejects_nonpositive_or_nonfinite_weights(weight: float) -> None:
    with pytest.raises(ValueError, match="weight"):
        _item(_rubric("bad weight"), weight)


def test_bank_requires_unique_members_unit_weights_and_one_score_contract() -> None:
    rubric = _rubric("same")
    with pytest.raises(ValueError, match="duplicate"):
        RubricBank(0, None, (_item(rubric, 0.5), _item(rubric, 0.5)))
    with pytest.raises(ValueError, match="sum to 1"):
        RubricBank(0, None, (_item(rubric, 0.9),))
    with pytest.raises(ValueError, match="normalization and scoring protocol"):
        RubricBank(
            0,
            None,
            (
                _item(_rubric("ordinal"), 0.5),
                _item(_rubric("binary", maximum=4, protocol="binary"), 0.5),
            ),
        )


def test_adaptive_source_must_be_exactly_the_previous_round() -> None:
    RubricBank(1, 0, (_item(_rubric("valid source"), 1.0),))
    with pytest.raises(ValueError, match="preceding"):
        RubricBank(2, 0, (_item(_rubric("stale source"), 1.0),))
    with pytest.raises(ValueError, match="preceding"):
        RubricBank(2, 2, (_item(_rubric("future source"), 1.0),))


def test_weighted_aggregate_preserves_noninteger_result() -> None:
    bank = _initial_bank()
    hashes = [item.rubric.content_sha256 for item in bank.items]

    assert bank.aggregate({hashes[0]: 41, hashes[1]: 80}) == 70.25
    assert bank.effective_sample_size == pytest.approx(1 / (0.25**2 + 0.75**2))
    with pytest.raises(ValueError, match="missing"):
        bank.aggregate({hashes[0]: 41})
    with pytest.raises(ValueError, match="finite"):
        bank.aggregate({hashes[0]: math.nan, hashes[1]: 80})


def test_lineage_allows_delete_add_retain_refine_and_split() -> None:
    prior = _initial_bank()
    first, second = (item.rubric for item in prior.items)
    replacement = RubricBank(
        1,
        0,
        (
            _item(first, 0.1, RubricLineage.RETAINED, first),
            _item(_rubric("split one"), 0.3, RubricLineage.REFINED, second),
            _item(_rubric("split two"), 0.4, RubricLineage.REFINED, second),
            _item(_rubric("new perspective"), 0.2),
        ),
    )

    replacement.validate_lineage(prior)

    invalid = RubricBank(
        1,
        0,
        (
            _item(first, 0.5, RubricLineage.RETAINED, first),
            _item(_rubric("also refine first"), 0.5, RubricLineage.REFINED, first),
        ),
    )
    with pytest.raises(ValueError, match="multiple descendants"):
        invalid.validate_lineage(prior)


def test_lineage_requires_immediately_prior_bank() -> None:
    initial = _initial_bank()
    replacement = RubricBank(
        2,
        1,
        (_item(_rubric("changed"), 1.0, RubricLineage.REFINED, initial.items[0].rubric),),
    )
    with pytest.raises(ValueError, match="immediately preceding"):
        replacement.validate_lineage(initial)


def test_policy_schedule_separates_fixed_nonadaptive_and_adaptive() -> None:
    initial = _initial_bank()
    RubricBankSchedule(
        RubricBankPolicy.FIXED,
        (RubricBankGeneration(initial, 0),),
    )
    nonadaptive = RubricBank(
        1,
        None,
        (_item(_rubric("replacement"), 1.0),),
    )
    RubricBankSchedule(
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        (RubricBankGeneration(initial, 0), RubricBankGeneration(nonadaptive, 3)),
    )
    adaptive = RubricBank(
        1,
        0,
        (_item(_rubric("adaptive"), 1.0),),
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

    assert manifest == tmp_path / "rubric-banks" / "bank-0000" / "manifest.json"
    payload = json.loads(manifest.read_text())
    assert payload["rubric_count"] == 2
    assert payload["effective_sample_size"] == pytest.approx(
        1 / (0.25**2 + 0.75**2)
    )
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

    member_path = next((manifest.parent / "members").iterdir())
    member_path.chmod(0o600)
    member_path.write_text(member_path.read_text() + "tamper\n")
    with pytest.raises(RuntimeError, match="invalid member"):
        load_rubric_bank(tmp_path, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [("rubric_count", 3), ("effective_sample_size", 99.0)],
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
        load_rubric_bank(
            tmp_path,
            0,
            expected_policy=RubricBankPolicy.FIXED,
        )


def test_bank_load_rejects_unexpected_empty_directories(tmp_path: Path) -> None:
    generation = RubricBankGeneration(_initial_bank(), proposer_call_budget=0)
    manifest = persist_rubric_bank(
        tmp_path,
        generation,
        RubricBankPolicy.FIXED,
    )
    manifest.parent.chmod(0o700)
    (manifest.parent / "unexpected").mkdir()

    with pytest.raises(RuntimeError, match="unexpected files"):
        load_rubric_bank(
            tmp_path,
            0,
            expected_policy=RubricBankPolicy.FIXED,
        )


def test_bank_load_rejects_duplicate_manifest_keys(tmp_path: Path) -> None:
    manifest = persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(_initial_bank(), proposer_call_budget=0),
        RubricBankPolicy.FIXED,
    )
    manifest.chmod(0o600)
    text = manifest.read_text()
    manifest.write_text(text.replace(
        '"policy": "fixed",',
        '"policy": "fixed",\n  "policy": "fixed",',
        1,
    ))

    with pytest.raises(RuntimeError, match="manifest is invalid"):
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
        persist_rubric_bank(
            tmp_path,
            generation,
            RubricBankPolicy.FIXED,
        )
    parent = tmp_path / "rubric-banks"
    assert not (parent / "bank-0000").exists()
    assert list(parent.iterdir()) == []


def test_persistence_rejects_policy_and_source_mismatches(tmp_path: Path) -> None:
    nonadaptive = RubricBank(
        1,
        None,
        (_item(_rubric("nonadaptive"), 1.0),),
    )
    with pytest.raises(ValueError, match="fixed policy"):
        persist_rubric_bank(
            tmp_path,
            RubricBankGeneration(nonadaptive, 2),
            RubricBankPolicy.FIXED,
        )

    adaptive = RubricBank(
        1,
        0,
        (_item(_rubric("adaptive"), 1.0),),
    )
    with pytest.raises(ValueError, match="nonadaptive"):
        persist_rubric_bank(
            tmp_path,
            RubricBankGeneration(adaptive, 2),
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        )
    with pytest.raises(ValueError, match="adaptive replacement"):
        persist_rubric_bank(
            tmp_path,
            RubricBankGeneration(nonadaptive, 2),
            RubricBankPolicy.ADAPTIVE_REPLACEMENT,
        )


def test_replacement_persistence_requires_exact_prior_lineage(tmp_path: Path) -> None:
    replacement = RubricBank(
        1,
        None,
        (_item(_rubric("new member"), 1.0),),
    )
    with pytest.raises(RuntimeError, match="directory is missing"):
        persist_rubric_bank(
            tmp_path,
            RubricBankGeneration(replacement, 2),
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        )

    prior = _initial_bank()
    persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(prior, 0),
        RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )
    foreign = _rubric("foreign prior")
    invalid_lineage = RubricBank(
        1,
        None,
        (
            _item(
                _rubric("invalid refinement"),
                1.0,
                RubricLineage.REFINED,
                foreign,
            ),
        ),
    )
    with pytest.raises(ValueError, match="absent from the prior bank"):
        persist_rubric_bank(
            tmp_path,
            RubricBankGeneration(invalid_lineage, 2),
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        )


@pytest.mark.parametrize(
    ("stored_policy", "bank", "tampered_policy"),
    [
        (
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            RubricBank(1, None, (_item(_rubric("fixed round"), 1.0),)),
            RubricBankPolicy.FIXED,
        ),
        (
            RubricBankPolicy.ADAPTIVE_REPLACEMENT,
            RubricBank(1, 0, (_item(_rubric("nonadaptive source"), 1.0),)),
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        ),
        (
            RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
            RubricBank(1, None, (_item(_rubric("adaptive source"), 1.0),)),
            RubricBankPolicy.ADAPTIVE_REPLACEMENT,
        ),
    ],
)
def test_bank_load_rejects_manifest_policy_source_mismatches(
    tmp_path: Path,
    stored_policy: RubricBankPolicy,
    bank: RubricBank,
    tampered_policy: RubricBankPolicy,
) -> None:
    persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(_initial_bank(), proposer_call_budget=0),
        stored_policy,
    )
    manifest = persist_rubric_bank(
        tmp_path,
        RubricBankGeneration(bank, proposer_call_budget=2),
        stored_policy,
    )
    manifest.chmod(0o600)
    payload = json.loads(manifest.read_text())
    payload["policy"] = tampered_policy.value
    manifest.write_text(json.dumps(payload))

    with pytest.raises(RuntimeError, match="invalid values"):
        load_rubric_bank(tmp_path, bank.generation_round)
