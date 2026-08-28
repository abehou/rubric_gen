"""Rubric-bank schedules and atomic generation storage."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from numbers import Real
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
    RubricCriterionMapping,
    RubricLineage,
    parse_elicited_criterion,
    require_nonnegative_int,
    require_sha256,
)


@dataclass(frozen=True)
class RubricBankGeneration:
    """Attach the predeclared proposer-call budget to one bank."""

    bank: RubricBank
    proposer_call_budget: int

    def __post_init__(self) -> None:
        if not isinstance(self.bank, RubricBank):
            raise ValueError("bank must be a RubricBank")
        require_nonnegative_int(
            self.proposer_call_budget,
            "proposer_call_budget",
        )


@dataclass(frozen=True)
class RubricBankSchedule:
    """Store and validate the bank generations for one policy arm."""

    policy: RubricBankPolicy
    generations: tuple[RubricBankGeneration, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.policy, RubricBankPolicy):
            raise ValueError("policy must be a RubricBankPolicy")
        if type(self.generations) is not tuple or not self.generations:
            raise ValueError("generations must be a non-empty tuple")
        if any(
            not isinstance(generation, RubricBankGeneration)
            for generation in self.generations
        ):
            raise ValueError("each generation must be a RubricBankGeneration")

        banks = tuple(generation.bank for generation in self.generations)
        if banks[0].generation_round != 0:
            raise ValueError("a schedule must start with generation round 0")
        for prior_bank, bank in zip(banks[:-1], banks[1:], strict=True):
            if bank.generation_round != prior_bank.generation_round + 1:
                raise ValueError("bank generation rounds must be consecutive")
            bank.validate_lineage(prior_bank)

        if self.policy is RubricBankPolicy.FIXED:
            if len(banks) != 1:
                raise ValueError("a fixed policy must contain only the initial bank")
            return

        if len(banks) < 2:
            raise ValueError("an elicitation policy must include an update")
        elicited_banks = banks[1:]
        if any(
            bank.rubric_count != 1
            or tuple(item.weight for item in bank.items) != (1.0,)
            for bank in elicited_banks
        ):
            raise ValueError(
                "an elicitation schedule requires one unit-weight rubric"
            )
        if self.policy is RubricBankPolicy.OFFLINE_ELICITATION:
            if len(banks) != 2:
                raise ValueError(
                    "offline elicitation must contain one pre-treatment update"
                )
            if any(bank.source_boundary is not None for bank in elicited_banks):
                raise ValueError(
                    "offline elicitation cannot use a live artifact boundary"
                )
        elif any(bank.source_boundary is None for bank in elicited_banks):
            raise ValueError(
                "each online elicitation update needs a live artifact boundary"
            )


def _validate_policy_bank(policy: RubricBankPolicy, bank: RubricBank) -> None:
    if policy is RubricBankPolicy.FIXED:
        if bank.generation_round != 0 or bank.source_boundary is not None:
            raise ValueError("a fixed policy can persist only the initial bank")
        return
    if bank.generation_round > 0 and (
        bank.rubric_count != 1
        or tuple(item.weight for item in bank.items) != (1.0,)
    ):
        raise ValueError(
            "an elicitation policy requires one unit-weight rubric"
        )
    if policy is RubricBankPolicy.OFFLINE_ELICITATION:
        if bank.generation_round > 1:
            raise ValueError(
                "offline elicitation permits one pre-treatment update"
            )
        if bank.source_boundary is not None:
            raise ValueError(
                "offline elicitation cannot use a live artifact boundary"
            )
        return
    if bank.generation_round == 0:
        if bank.source_boundary is not None:
            raise ValueError("the initial adaptive bank cannot use a source boundary")
    elif bank.source_boundary != bank.generation_round:
        raise ValueError(
            "online elicitation must use the matching live artifact boundary"
        )


_BANK_MANIFEST_KEYS = frozenset({
    "policy",
    "generation_round",
    "source_boundary",
    "proposer_call_budget",
    "bank_sha256",
    "rubric_count",
    "inverse_weight_concentration",
    "specification_anchor",
    "members",
})
_BANK_ANCHOR_KEYS = frozenset({
    "content_sha256",
    "lineage",
    "prior_content_sha256",
    "path",
})
_BANK_MEMBER_KEYS = frozenset({
    "content_sha256",
    "weight",
    "lineage",
    "prior_content_sha256",
    "criterion_map",
    "elicited_criteria",
    "path",
})
_CRITERION_MAPPING_KEYS = frozenset({
    "anchor_criterion_id",
    "member_criterion_id",
})


def rubric_bank_directory(root: Path, generation_round: int) -> Path:
    """Return the canonical directory for one complete bank generation."""

    require_nonnegative_int(generation_round, "generation_round")
    return root / "rubric-banks" / f"bank-{generation_round:04d}"


def persist_rubric_bank(
    root: Path,
    generation: RubricBankGeneration,
    policy: RubricBankPolicy,
) -> Path:
    """Persist one immutable complete bank and return its manifest path."""

    if not isinstance(generation, RubricBankGeneration):
        raise ValueError("generation must be a RubricBankGeneration")
    if not isinstance(policy, RubricBankPolicy):
        raise ValueError("policy must be a RubricBankPolicy")
    bank = generation.bank
    _validate_policy_bank(policy, bank)
    if bank.generation_round > 0:
        prior = load_rubric_bank(
            root,
            bank.generation_round - 1,
            expected_policy=policy,
        )
        bank.validate_lineage(prior.bank)
    bank_dir = rubric_bank_directory(root, bank.generation_round)
    manifest_path = bank_dir / "manifest.json"
    if os.path.lexists(bank_dir):
        loaded = load_rubric_bank(root, bank.generation_round, expected_policy=policy)
        if loaded != generation:
            raise RuntimeError("persisted rubric bank differs from the requested bank")
        return manifest_path

    bank_parent = bank_dir.parent
    bank_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(
        prefix=f".bank-{bank.generation_round:04d}.",
        dir=bank_parent,
    ))
    try:
        anchor_path = stage / "specification-anchor.txt"
        anchor_path.write_text(bank.specification_anchor.content, encoding="utf-8")
        members_dir = stage / "members"
        members_dir.mkdir()
        members: list[dict[str, object]] = []
        for item in bank.items:
            relative_path = Path("members") / f"{item.rubric.content_sha256}.txt"
            member_path = stage / relative_path
            member_path.write_text(item.rubric.content, encoding="utf-8")
            members.append({
                "content_sha256": item.rubric.content_sha256,
                "weight": item.weight,
                "lineage": item.lineage.value,
                "prior_content_sha256": item.prior_content_sha256,
                "criterion_map": [
                    mapping.as_dict() for mapping in item.criterion_map
                ],
                "elicited_criteria": [
                    criterion.as_dict()
                    for criterion in item.elicited_criteria
                ],
                "path": relative_path.as_posix(),
            })
        write_json_atomic(stage / "manifest.json", {
            "policy": policy.value,
            "generation_round": bank.generation_round,
            "source_boundary": bank.source_boundary,
            "proposer_call_budget": generation.proposer_call_budget,
            "bank_sha256": bank.content_sha256,
            "rubric_count": bank.rubric_count,
            "inverse_weight_concentration": bank.inverse_weight_concentration,
            "specification_anchor": {
                "content_sha256": bank.specification_anchor.content_sha256,
                "lineage": bank.specification_anchor_lineage.value,
                "prior_content_sha256": (
                    bank.prior_specification_anchor_sha256
                ),
                "path": anchor_path.name,
            },
            "members": members,
        })
        staged = _load_rubric_bank_directory(
            stage,
            bank.generation_round,
            expected_policy=policy,
        )
        if staged != generation:
            raise RuntimeError("staged rubric bank differs from the requested bank")
        for path in (
            stage / "manifest.json",
            anchor_path,
            *members_dir.iterdir(),
        ):
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        for directory in (members_dir, stage):
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        os.rename(stage, bank_dir)
        directory_fd = os.open(bank_parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return manifest_path


def load_rubric_bank(
    root: Path,
    generation_round: int,
    *,
    expected_policy: RubricBankPolicy | None = None,
) -> RubricBankGeneration:
    """Load and validate one immutable complete bank generation."""

    bank_dir = rubric_bank_directory(root, generation_round)
    return _load_rubric_bank_directory(
        bank_dir,
        generation_round,
        expected_policy=expected_policy,
    )


@dataclass(frozen=True)
class _LoadedManifest:
    value: dict[str, object]
    policy: RubricBankPolicy
    members: tuple[object, ...]
    manifest_path: Path
    members_dir: Path


@dataclass(frozen=True)
class _LoadedAnchor:
    rubric: CompleteRubric
    lineage: RubricLineage
    prior_content_sha256: str | None
    path: Path


def _load_manifest(
    bank_dir: Path,
    generation_round: int,
    expected_policy: RubricBankPolicy | None,
) -> _LoadedManifest:
    manifest_path = bank_dir / "manifest.json"
    if bank_dir.is_symlink() or not bank_dir.is_dir():
        raise RuntimeError(f"rubric bank directory is missing: {bank_dir}")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"rubric bank manifest is missing: {manifest_path}")
    try:
        value = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"rubric bank manifest is invalid: {manifest_path}") from exc
    if not isinstance(value, dict) or set(value) != _BANK_MANIFEST_KEYS:
        raise RuntimeError("rubric bank manifest has invalid fields")
    try:
        policy = RubricBankPolicy(value["policy"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("rubric bank manifest has an invalid policy") from exc
    if expected_policy is not None and policy is not expected_policy:
        raise RuntimeError("rubric bank manifest has the wrong policy")
    if value["generation_round"] != generation_round:
        raise RuntimeError("rubric bank manifest has the wrong generation round")
    members = value["members"]
    if not isinstance(members, list) or not members:
        raise RuntimeError("rubric bank manifest has invalid members")
    members_dir = bank_dir / "members"
    if members_dir.is_symlink() or not members_dir.is_dir():
        raise RuntimeError("rubric bank members directory is invalid")
    return _LoadedManifest(
        value=value,
        policy=policy,
        members=tuple(members),
        manifest_path=manifest_path,
        members_dir=members_dir,
    )


def _load_anchor(bank_dir: Path, value: object) -> _LoadedAnchor:
    if not isinstance(value, dict) or set(value) != _BANK_ANCHOR_KEYS:
        raise RuntimeError("rubric bank manifest has an invalid specification anchor")
    try:
        digest = require_sha256(
            value["content_sha256"],
            "specification_anchor.content_sha256",
        )
        relative_path = Path(value["path"])
        if relative_path != Path("specification-anchor.txt"):
            raise ValueError("specification anchor path is not canonical")
        path = bank_dir / relative_path
        if path.is_symlink() or not path.is_file():
            raise ValueError("specification anchor rubric is missing")
        prior_digest = value["prior_content_sha256"]
        if prior_digest is not None:
            prior_digest = require_sha256(
                prior_digest,
                "specification_anchor.prior_content_sha256",
            )
        return _LoadedAnchor(
            rubric=CompleteRubric(
                content=path.read_text(encoding="utf-8"),
                content_sha256=digest,
            ),
            lineage=RubricLineage(value["lineage"]),
            prior_content_sha256=prior_digest,
            path=path,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "rubric bank manifest has an invalid specification anchor"
        ) from exc


def _load_criterion_mapping(value: object) -> RubricCriterionMapping:
    if not isinstance(value, dict) or set(value) != _CRITERION_MAPPING_KEYS:
        raise ValueError("member criterion mapping is invalid")
    return RubricCriterionMapping(
        anchor_criterion_id=value["anchor_criterion_id"],
        member_criterion_id=value["member_criterion_id"],
    )


def _load_member(
    bank_dir: Path,
    value: object,
) -> tuple[RubricBankItem, Path]:
    if not isinstance(value, dict) or set(value) != _BANK_MEMBER_KEYS:
        raise RuntimeError("rubric bank manifest has an invalid member")
    try:
        digest = require_sha256(value["content_sha256"], "content_sha256")
        relative_path = Path(value["path"])
        expected_path = Path("members") / f"{digest}.txt"
        if relative_path != expected_path:
            raise ValueError("member path is not canonical")
        path = bank_dir / relative_path
        if path.is_symlink() or not path.is_file():
            raise ValueError("member rubric is missing")
        criterion_map = value["criterion_map"]
        if not isinstance(criterion_map, list):
            raise ValueError("member criterion map is invalid")
        elicited_criteria = value["elicited_criteria"]
        if not isinstance(elicited_criteria, list):
            raise ValueError("member elicited criteria are invalid")
        return (
            RubricBankItem(
                rubric=CompleteRubric(
                    content=path.read_text(encoding="utf-8"),
                    content_sha256=digest,
                ),
                weight=value["weight"],
                lineage=RubricLineage(value["lineage"]),
                criterion_map=tuple(
                    _load_criterion_mapping(mapping)
                    for mapping in criterion_map
                ),
                prior_content_sha256=value["prior_content_sha256"],
                elicited_criteria=tuple(
                    parse_elicited_criterion(criterion)
                    for criterion in elicited_criteria
                ),
            ),
            path,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise RuntimeError("rubric bank manifest has an invalid member") from exc


def _build_generation(
    manifest: _LoadedManifest,
    anchor: _LoadedAnchor,
    items: tuple[RubricBankItem, ...],
    generation_round: int,
) -> RubricBankGeneration:
    try:
        bank = RubricBank(
            generation_round=generation_round,
            source_boundary=manifest.value["source_boundary"],
            specification_anchor=anchor.rubric,
            specification_anchor_lineage=anchor.lineage,
            prior_specification_anchor_sha256=anchor.prior_content_sha256,
            items=items,
        )
        generation = RubricBankGeneration(
            bank=bank,
            proposer_call_budget=manifest.value["proposer_call_budget"],
        )
        _validate_policy_bank(manifest.policy, bank)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("rubric bank manifest has invalid values") from exc
    return generation


def _validate_manifest_statistics(
    value: dict[str, object],
    bank: RubricBank,
) -> None:
    if value["bank_sha256"] != bank.content_sha256:
        raise RuntimeError("rubric bank manifest has the wrong bank hash")
    concentration = value["inverse_weight_concentration"]
    if (
        type(value["rubric_count"]) is not int
        or value["rubric_count"] != bank.rubric_count
        or isinstance(concentration, bool)
        or not isinstance(concentration, Real)
        or not math.isfinite(float(concentration))
        or float(concentration) != bank.inverse_weight_concentration
    ):
        raise RuntimeError("rubric bank manifest has invalid derived statistics")


def _load_rubric_bank_directory(
    bank_dir: Path,
    generation_round: int,
    *,
    expected_policy: RubricBankPolicy | None,
) -> RubricBankGeneration:
    """Load one bank from its final or unpublished staged directory."""

    manifest = _load_manifest(bank_dir, generation_round, expected_policy)
    anchor = _load_anchor(bank_dir, manifest.value["specification_anchor"])
    loaded_members = tuple(
        _load_member(bank_dir, value) for value in manifest.members
    )
    expected_files = {
        manifest.manifest_path,
        anchor.path,
        *(path for _, path in loaded_members),
    }
    if set(bank_dir.rglob("*")) != expected_files | {manifest.members_dir}:
        raise RuntimeError("rubric bank directory contains unexpected files")
    generation = _build_generation(
        manifest,
        anchor,
        tuple(item for item, _ in loaded_members),
        generation_round,
    )
    _validate_manifest_statistics(manifest.value, generation.bank)
    return generation


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value
