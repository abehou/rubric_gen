"""Immutable single-rubric generations and elicitation-policy validation."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.artifacts import make_read_only
from rubric_gen.submission_revision.autorubric import (
    AutoRubricAdapterError,
    parse_autorubric_rubric,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_RUBRIC_BANK_ITEMS = 1
MAX_ELICITED_CRITERIA = 5
ELICITED_CRITERION_PENALTY_FRACTION = 0.04
MAX_CRITERION_TITLE_CHARS = 160
MAX_CRITERION_TEXT_CHARS = 1_000
_SCORING_PROTOCOL_PREFIX = "Scoring protocol: "
_ELICITED_CLAIM_SCOPE = (
    "Apply this penalty only when the submission claims or relies on this "
    "property. Do not penalize an unclaimed optional feature. "
)
_ELICITED_PASS_SCOPE = "No covered claim is made, or the check passes: "
_ELICITED_FAILURE_SCOPE = (
    "The submission claims or relies on the property, but the check fails: "
)


def _require_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _scoring_protocol(rubric_text: str) -> str | None:
    values = [
        line.removeprefix(_SCORING_PROTOCOL_PREFIX)
        for line in rubric_text.splitlines()
        if line.startswith(_SCORING_PROTOCOL_PREFIX)
    ]
    if not values:
        return None
    if len(values) != 1 or not values[0] or values[0] != values[0].strip():
        raise ValueError("rubric has an invalid scoring protocol directive")
    return values[0]


def _validate_complete_rubric(rubric_text: str) -> tuple[str | None, int]:
    """Validate the current complete-rubric grammar and score contract."""

    try:
        parsed = parse_autorubric_rubric(rubric_text)
    except AutoRubricAdapterError as exc:
        raise ValueError(f"rubric is not structurally complete: {exc}") from exc
    criterion_ids = [criterion.criterion_id for criterion in parsed.criteria]
    if criterion_ids != [
        f"criterion_{index}" for index in range(1, len(criterion_ids) + 1)
    ]:
        raise ValueError("complete rubric criterion numbers must be contiguous")
    titles = [" ".join(criterion.title.lower().split()) for criterion in parsed.criteria]
    if len(set(titles)) != len(titles):
        raise ValueError("complete rubric contains duplicate criterion titles")

    protocol = _scoring_protocol(rubric_text)
    expected_maximum = parsed.normalization_maximum or 100
    total_maximum = 0
    for criterion in parsed.criteria:
        labels = [level.label for level in criterion.levels]
        expected_labels = [
            chr(ord("A") + index) for index in range(len(labels))
        ]
        if labels != (["A", "B"] if protocol is not None else expected_labels):
            raise ValueError(
                f"{criterion.criterion_id} has invalid ordered level labels"
            )
        if protocol is None and len(labels) < 3:
            raise ValueError(
                f"{criterion.criterion_id} must contain at least three levels"
            )
        points = [level.points for level in criterion.levels]
        if (
            any(left <= right for left, right in zip(points, points[1:]))
            or points[0] < 0
            or points.count(0) != 1
        ):
            raise ValueError(
                f"{criterion.criterion_id} has invalid ordered level points"
            )
        total_maximum += points[0]
    if total_maximum != expected_maximum:
        raise ValueError(
            "complete rubric top-level points do not match its score maximum"
        )
    return protocol, expected_maximum


class RubricLineage(str, Enum):
    """Describe how one rubric relates to the prior bank."""

    NEW = "new"
    REFINED = "refined"
    RETAINED = "retained"


class RubricBankPolicy(str, Enum):
    """Define how an experiment changes its single rubric."""

    FIXED = "fixed"
    OFFLINE_ELICITATION = "offline_elicitation"
    ONLINE_ELICITATION = "online_elicitation"


@dataclass(frozen=True)
class CompleteRubric:
    """Store one complete rubric and its verified content hash."""

    content: str
    content_sha256: str

    def __post_init__(self) -> None:
        if type(self.content) is not str or not self.content.strip():
            raise ValueError("rubric content must be a non-empty string")
        _require_sha256(self.content_sha256, "content_sha256")
        if sha256_text(self.content) != self.content_sha256:
            raise ValueError("content_sha256 does not match rubric content")
        _validate_complete_rubric(self.content)

    @classmethod
    def from_content(cls, content: str) -> CompleteRubric:
        """Create a rubric with the hash of its exact UTF-8 content."""

        if type(content) is not str:
            raise ValueError("rubric content must be a string")
        return cls(content=content, content_sha256=sha256_text(content))


@dataclass(frozen=True)
class RubricCriterionMapping:
    """Map one anchor criterion to one member criterion."""

    anchor_criterion_id: str
    member_criterion_id: str

    def __post_init__(self) -> None:
        if (
            type(self.anchor_criterion_id) is not str
            or re.fullmatch(r"criterion_[1-9][0-9]*", self.anchor_criterion_id)
            is None
        ):
            raise ValueError("criterion mapping has an invalid anchor criterion ID")
        if (
            type(self.member_criterion_id) is not str
            or re.fullmatch(r"criterion_[1-9][0-9]*", self.member_criterion_id)
            is None
        ):
            raise ValueError("criterion mapping has an invalid member criterion ID")

    def as_dict(self) -> dict[str, object]:
        """Return the canonical JSON representation."""

        return {
            "anchor_criterion_id": self.anchor_criterion_id,
            "member_criterion_id": self.member_criterion_id,
        }


def is_valid_single_line_text(
    value: object,
    *,
    max_chars: int | None = None,
) -> bool:
    """Return true for canonical printable text with no hidden line boundary."""

    return bool(
        type(value) is str
        and value
        and value == value.strip()
        and (max_chars is None or len(value) <= max_chars)
        and len(value.splitlines()) == 1
        and not any(
            unicodedata.category(character).startswith("C")
            for character in value
        )
    )


def _require_criterion_text(
    value: object,
    field_name: str,
    *,
    max_chars: int,
) -> str:
    if (
        not is_valid_single_line_text(value, max_chars=max_chars)
    ):
        raise ValueError(
            f"{field_name} must be printable single-line text of at most "
            f"{max_chars} characters"
        )
    assert isinstance(value, str)
    return value


@dataclass(frozen=True)
class ElicitedCriterion:
    """Store one general criterion induced from a blinded artifact history."""

    criterion_id: str
    title: str
    requirement: str
    level_descriptions: tuple[tuple[str, str], ...]
    support_pair_ids: tuple[str, ...]
    source_generation: int

    def __post_init__(self) -> None:
        if (
            type(self.criterion_id) is not str
            or re.fullmatch(r"elicited_[0-9a-f]{16}", self.criterion_id) is None
        ):
            raise ValueError("elicited criterion has an invalid ID")
        _require_criterion_text(
            self.title,
            "elicited criterion title",
            max_chars=MAX_CRITERION_TITLE_CHARS,
        )
        _require_criterion_text(
            self.requirement,
            "elicited criterion requirement",
            max_chars=MAX_CRITERION_TEXT_CHARS,
        )
        if (
            type(self.level_descriptions) is not tuple
            or len(self.level_descriptions) < 2
            or any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or len(item[0]) != 1
                or not item[0].isupper()
                or not is_valid_single_line_text(
                    item[1], max_chars=MAX_CRITERION_TEXT_CHARS
                )
                for item in self.level_descriptions
            )
        ):
            raise ValueError("elicited criterion levels are invalid")
        labels = tuple(label for label, _ in self.level_descriptions)
        if labels != tuple(
            chr(ord("A") + index) for index in range(len(labels))
        ):
            raise ValueError("elicited criterion level labels are not contiguous")
        if (
            type(self.support_pair_ids) is not tuple
            or len(self.support_pair_ids) < 2
            or len(set(self.support_pair_ids)) != len(self.support_pair_ids)
            or any(
                type(pair_id) is not str
                or re.fullmatch(r"pair_[0-9a-f]{16}", pair_id) is None
                for pair_id in self.support_pair_ids
            )
        ):
            raise ValueError("elicited criterion needs two distinct artifact pairs")
        _require_nonnegative_int(self.source_generation, "source_generation")
        expected_id = "elicited_" + sha256_text(json.dumps(
            {
                "title": self.title,
                "requirement": self.requirement,
                "level_descriptions": self.level_descriptions,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ))[:16]
        if self.criterion_id != expected_id:
            raise ValueError("elicited criterion ID does not match its content")

    @classmethod
    def create(
        cls,
        *,
        title: str,
        requirement: str,
        level_descriptions: tuple[tuple[str, str], ...],
        support_pair_ids: tuple[str, ...],
        source_generation: int,
    ) -> "ElicitedCriterion":
        payload = json.dumps(
            {
                "title": title,
                "requirement": requirement,
                "level_descriptions": level_descriptions,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return cls(
            criterion_id="elicited_" + sha256_text(payload)[:16],
            title=title,
            requirement=requirement,
            level_descriptions=level_descriptions,
            support_pair_ids=support_pair_ids,
            source_generation=source_generation,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "title": self.title,
            "requirement": self.requirement,
            "level_descriptions": [
                {"label": label, "description": description}
                for label, description in self.level_descriptions
            ],
            "support_pair_ids": list(self.support_pair_ids),
            "source_generation": self.source_generation,
        }


def parse_elicited_criterion(value: object) -> ElicitedCriterion:
    if not isinstance(value, dict) or set(value) != {
        "criterion_id",
        "title",
        "requirement",
        "level_descriptions",
        "support_pair_ids",
        "source_generation",
    }:
        raise ValueError("elicited criterion has invalid fields")
    raw_levels = value.get("level_descriptions")
    if not isinstance(raw_levels, list):
        raise ValueError("elicited criterion levels must be a list")
    levels: list[tuple[str, str]] = []
    for level in raw_levels:
        if not isinstance(level, dict) or set(level) != {"label", "description"}:
            raise ValueError("elicited criterion level has invalid fields")
        levels.append((level["label"], level["description"]))  # type: ignore[arg-type]
    raw_support = value.get("support_pair_ids")
    if not isinstance(raw_support, list):
        raise ValueError("elicited criterion support must be a list")
    return ElicitedCriterion(
        criterion_id=value.get("criterion_id"),  # type: ignore[arg-type]
        title=value.get("title"),  # type: ignore[arg-type]
        requirement=value.get("requirement"),  # type: ignore[arg-type]
        level_descriptions=tuple(levels),
        support_pair_ids=tuple(raw_support),  # type: ignore[arg-type]
        source_generation=value.get("source_generation"),  # type: ignore[arg-type]
    )


def _rubric_point_vectors(
    rubric: CompleteRubric,
) -> dict[str, tuple[tuple[str, int], ...]]:
    parsed = parse_autorubric_rubric(rubric.content)
    return {
        criterion.criterion_id: tuple(
            (level.label, level.points) for level in criterion.levels
        )
        for criterion in parsed.criteria
    }


def identity_criterion_map(
    rubric: CompleteRubric,
) -> tuple[RubricCriterionMapping, ...]:
    """Return the exact identity map for one rubric used as its own anchor."""

    return tuple(
        RubricCriterionMapping(criterion_id, criterion_id)
        for criterion_id in _rubric_point_vectors(rubric)
    )


def _criterion_specific_requirement(
    criterion: object,
) -> str:
    criterion_id = getattr(criterion, "criterion_id")
    title = getattr(criterion, "title")
    number = criterion_id.removeprefix("criterion_")
    marker = f"Criterion {number}: {title}"
    requirement = getattr(criterion, "requirement")
    if requirement.startswith(marker):
        suffix = requirement[len(marker):]
    else:
        separator = f"\n\n{marker}"
        marker_offset = requirement.find(separator)
        if marker_offset < 0:
            raise ValueError(
                f"{criterion_id} lacks its canonical requirement marker"
            )
        suffix = requirement[marker_offset + len(separator):]
    if suffix.startswith("\n\n"):
        suffix = suffix[2:]
    elif suffix:
        raise ValueError(f"{criterion_id} lacks its canonical requirement marker")
    return suffix.strip()


def _context_with_normalization_maximum(
    context: str,
    *,
    new_maximum: int,
) -> str:
    """Return context with one authoritative percentage denominator."""

    lines = context.splitlines()
    normalization_prefix = "Score normalization maximum:"
    normalization_pattern = re.compile(
        r"^[ \t]*Score normalization maximum:[ \t]*[1-9]\d*[ \t]*$"
    )
    total_points_pattern = re.compile(r"^[ \t]*Total Points:[ \t]*\d+[ \t]*$")
    output: list[str] = []
    found_normalization = False
    for line in lines:
        if normalization_pattern.fullmatch(line):
            if found_normalization:
                raise ValueError("rubric has duplicate normalization directives")
            output.append(f"{normalization_prefix} {new_maximum}")
            found_normalization = True
        elif total_points_pattern.fullmatch(line):
            output.append(f"Total Points: {new_maximum}")
        else:
            output.append(line)
    if not found_normalization:
        if output and output[-1]:
            output.append("")
        output.append(f"{normalization_prefix} {new_maximum}")
    return "\n".join(output)


def render_augmented_rubric(
    original_rubric: CompleteRubric,
    elicited_criteria: tuple[ElicitedCriterion, ...],
) -> tuple[CompleteRubric, tuple[RubricCriterionMapping, ...]]:
    """Render one rubric with fixed original text and bounded added criteria."""

    if not isinstance(original_rubric, CompleteRubric):
        raise ValueError("original_rubric must be a CompleteRubric")
    if (
        type(elicited_criteria) is not tuple
        or len(elicited_criteria) > MAX_ELICITED_CRITERIA
        or any(not isinstance(item, ElicitedCriterion) for item in elicited_criteria)
    ):
        raise ValueError("elicited_criteria has an invalid value")
    if len({item.criterion_id for item in elicited_criteria}) != len(
        elicited_criteria
    ):
        raise ValueError("elicited criteria repeat a content identity")
    if not elicited_criteria:
        return original_rubric, identity_criterion_map(original_rubric)

    parsed = parse_autorubric_rubric(original_rubric.content)
    protocol = _scoring_protocol(original_rubric.content)
    required_labels = ("A", "B") if protocol is not None else ("A", "B", "C")
    if len(elicited_criteria) > elicited_criterion_capacity(original_rubric):
        raise ValueError("elicited criteria exceed the penalty capacity")
    for criterion in elicited_criteria:
        if tuple(label for label, _ in criterion.level_descriptions) != required_labels:
            raise ValueError(
                "elicited criterion levels do not match the rubric scoring protocol"
            )
    titles = [" ".join(item.title.casefold().split()) for item in elicited_criteria]
    original_titles = {
        " ".join(criterion.title.casefold().split()) for criterion in parsed.criteria
    }
    if len(set(titles)) != len(titles) or set(titles) & original_titles:
        raise ValueError("elicited criteria contain duplicate criterion titles")

    original_maximum = parsed.normalization_maximum or 100
    penalty_points = elicited_criterion_penalty_points(original_rubric)

    lines: list[str] = []
    if parsed.context:
        lines.extend((
            _context_with_normalization_maximum(
                parsed.context,
                new_maximum=original_maximum,
            ),
            "",
        ))
    else:
        lines.extend((
            f"Score normalization maximum: {original_maximum}",
            "",
        ))
    criterion_map: list[RubricCriterionMapping] = []
    for index, criterion in enumerate(parsed.criteria, start=1):
        member_id = f"criterion_{index}"
        criterion_map.append(RubricCriterionMapping(
            anchor_criterion_id=criterion.criterion_id,
            member_criterion_id=member_id,
        ))
        lines.append(f"Criterion {index}: {criterion.title}")
        specific = _criterion_specific_requirement(criterion)
        if specific:
            lines.append(specific)
        lines.append(
            "Levels: " + " ".join(
                f"{level.label}={level.points}"
                for level in criterion.levels
            )
        )
        lines.extend(
            f"[{level.label}]: {level.description}"
            for level in criterion.levels
        )
        lines.append("")

    offset = len(parsed.criteria)
    for index, criterion in enumerate(elicited_criteria, start=1):
        number = offset + index
        labels = tuple(label for label, _ in criterion.level_descriptions)
        points = (
            (0, -penalty_points)
            if labels == ("A", "B")
            else (0, -max(1, penalty_points // 2), -penalty_points)
        )
        lines.extend((
            f"Criterion {number}: {criterion.title}",
            _ELICITED_CLAIM_SCOPE + criterion.requirement,
            f"Elicited criterion ID: {criterion.criterion_id}",
            "Levels: " + " ".join(
                f"{label}={point}"
                for label, point in zip(labels, points, strict=True)
            ),
        ))
        lines.extend(
            f"[{label}]: "
            + (
                _ELICITED_PASS_SCOPE
                if label == "A"
                else _ELICITED_FAILURE_SCOPE
            )
            + description
            for label, description in criterion.level_descriptions
        )
        lines.append("")
    rubric = CompleteRubric.from_content("\n".join(lines).rstrip() + "\n")
    return rubric, tuple(criterion_map)


def elicited_criterion_penalty_points(original_rubric: CompleteRubric) -> int:
    """Return the fixed maximum penalty for each elicited criterion."""

    if not isinstance(original_rubric, CompleteRubric):
        raise ValueError("original_rubric must be a CompleteRubric")
    parsed = parse_autorubric_rubric(original_rubric.content)
    original_maximum = parsed.normalization_maximum or 100
    minimum = 1 if _scoring_protocol(original_rubric.content) is not None else 2
    return max(
        minimum,
        round(original_maximum * ELICITED_CRITERION_PENALTY_FRACTION),
    )


def elicited_criterion_capacity(original_rubric: CompleteRubric) -> int:
    """Return the criterion cap that keeps total penalties near 20 percent."""

    if not isinstance(original_rubric, CompleteRubric):
        raise ValueError("original_rubric must be a CompleteRubric")
    parsed = parse_autorubric_rubric(original_rubric.content)
    original_maximum = parsed.normalization_maximum or 100
    penalty_points = elicited_criterion_penalty_points(original_rubric)
    minimum = 1 if _scoring_protocol(original_rubric.content) is not None else 2
    total_penalty = max(
        minimum,
        round(
            original_maximum
            * ELICITED_CRITERION_PENALTY_FRACTION
            * MAX_ELICITED_CRITERIA
        ),
    )
    return min(
        MAX_ELICITED_CRITERIA,
        max(1, round(total_penalty / penalty_points)),
    )


def validate_rubric_criterion_map(
    specification_anchor: CompleteRubric,
    rubric: CompleteRubric,
    criterion_map: tuple[RubricCriterionMapping, ...],
    elicited_criteria: tuple[ElicitedCriterion, ...],
) -> None:
    """Require the exact deterministic rendering of one augmented rubric."""

    if not isinstance(specification_anchor, CompleteRubric):
        raise ValueError("specification anchor must be a CompleteRubric")
    if not isinstance(rubric, CompleteRubric):
        raise ValueError("rubric must be a CompleteRubric")
    if (
        type(criterion_map) is not tuple
        or any(not isinstance(item, RubricCriterionMapping) for item in criterion_map)
    ):
        raise ValueError("criterion_map must contain RubricCriterionMapping values")
    expected_rubric, expected_map = render_augmented_rubric(
        specification_anchor,
        elicited_criteria,
    )
    if rubric != expected_rubric or criterion_map != expected_map:
        raise ValueError("rubric differs from its deterministic augmentation")


def rubric_bank_member_limits(
    specification_anchor: CompleteRubric,
    generation_round: int,
) -> tuple[int, int]:
    """Return the structural bank-size bounds for one anchor and round."""

    generation_round = _require_nonnegative_int(
        generation_round,
        "generation_round",
    )
    return (1, 1)


@dataclass(frozen=True)
class RubricBankItem:
    """Store the sole rubric and its cumulative elicited criteria."""

    rubric: CompleteRubric
    weight: float
    lineage: RubricLineage
    criterion_map: tuple[RubricCriterionMapping, ...]
    prior_content_sha256: str | None = None
    elicited_criteria: tuple[ElicitedCriterion, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.rubric, CompleteRubric):
            raise ValueError("rubric must be a CompleteRubric")
        if isinstance(self.weight, bool) or not isinstance(self.weight, Real):
            raise ValueError("weight must be a real number")
        weight = float(self.weight)
        if not math.isfinite(weight) or weight <= 0.0:
            raise ValueError("weight must be finite and positive")
        object.__setattr__(self, "weight", weight)

        if not isinstance(self.lineage, RubricLineage):
            raise ValueError("lineage must be a RubricLineage")
        if (
            type(self.criterion_map) is not tuple
            or any(
                not isinstance(mapping, RubricCriterionMapping)
                for mapping in self.criterion_map
            )
        ):
            raise ValueError(
                "criterion_map must contain RubricCriterionMapping values"
            )
        if (
            type(self.elicited_criteria) is not tuple
            or len(self.elicited_criteria) > MAX_ELICITED_CRITERIA
            or any(
                not isinstance(criterion, ElicitedCriterion)
                for criterion in self.elicited_criteria
            )
        ):
            raise ValueError("elicited_criteria has an invalid value")
        if len({
            criterion.criterion_id for criterion in self.elicited_criteria
        }) != len(self.elicited_criteria):
            raise ValueError("elicited_criteria contains duplicate criteria")
        if self.lineage is RubricLineage.NEW:
            if self.prior_content_sha256 is not None:
                raise ValueError("a new rubric cannot reference a prior rubric")
            if self.elicited_criteria:
                raise ValueError("the initial rubric cannot contain elicited criteria")
            return

        prior_hash = _require_sha256(
            self.prior_content_sha256,
            "prior_content_sha256",
        )
        if self.lineage is RubricLineage.RETAINED:
            if prior_hash != self.rubric.content_sha256:
                raise ValueError("a retained rubric must keep the prior content hash")
        elif prior_hash == self.rubric.content_sha256:
            raise ValueError("a refined rubric must change the prior content hash")


@dataclass(frozen=True)
class RubricBank:
    """Store one task rubric for a generation round."""

    generation_round: int
    source_boundary: int | None
    specification_anchor: CompleteRubric
    specification_anchor_lineage: RubricLineage
    prior_specification_anchor_sha256: str | None
    items: tuple[RubricBankItem, ...]

    def __post_init__(self) -> None:
        generation_round = _require_nonnegative_int(
            self.generation_round,
            "generation_round",
        )
        if self.source_boundary is not None:
            source_boundary = _require_nonnegative_int(
                self.source_boundary,
                "source_boundary",
            )
            if source_boundary != generation_round:
                raise ValueError(
                    "source_boundary must equal the elicitation generation round"
                )
        if generation_round == 0 and self.source_boundary is not None:
            raise ValueError("the initial bank cannot have a source boundary")

        if not isinstance(self.specification_anchor, CompleteRubric):
            raise ValueError("specification_anchor must be a CompleteRubric")
        if not isinstance(self.specification_anchor_lineage, RubricLineage):
            raise ValueError("specification_anchor_lineage must be a RubricLineage")
        if generation_round == 0:
            if (
                self.specification_anchor_lineage is not RubricLineage.NEW
                or self.prior_specification_anchor_sha256 is not None
            ):
                raise ValueError("the initial specification anchor must have new lineage")
        else:
            if self.specification_anchor_lineage is not RubricLineage.RETAINED:
                raise ValueError("the original rubric must remain retained")
            prior_anchor_hash = _require_sha256(
                self.prior_specification_anchor_sha256,
                "prior_specification_anchor_sha256",
            )
            if prior_anchor_hash != self.specification_anchor.content_sha256:
                raise ValueError("the original rubric hash cannot change")

        minimum_items, maximum_items = rubric_bank_member_limits(
            self.specification_anchor,
            generation_round,
        )
        if (
            type(self.items) is not tuple
            or not minimum_items <= len(self.items) <= maximum_items
        ):
            raise ValueError(
                "items must contain "
                f"{minimum_items} to {maximum_items} complete rubrics"
            )
        if any(not isinstance(item, RubricBankItem) for item in self.items):
            raise ValueError("each bank item must be a RubricBankItem")

        rubric_hashes = [item.rubric.content_sha256 for item in self.items]
        if len(set(rubric_hashes)) != len(rubric_hashes):
            raise ValueError("a bank cannot contain duplicate rubric hashes")
        if rubric_hashes != sorted(rubric_hashes):
            raise ValueError(
                "bank members must use ascending rubric content hash order"
            )

        if self.items[0].weight != 1.0:
            raise ValueError("the sole rubric member must have weight 1")
        if generation_round == 0 and any(
            item.lineage is not RubricLineage.NEW for item in self.items
        ):
            raise ValueError("each rubric in the initial bank must have new lineage")

        if generation_round == 0:
            if (
                len(self.items) != 1
                or self.items[0].rubric != self.specification_anchor
                or self.items[0].criterion_map
                != identity_criterion_map(self.specification_anchor)
                or self.items[0].elicited_criteria
            ):
                raise ValueError(
                    "the initial bank must contain the unchanged original rubric"
                )

        protocols = {
            _validate_complete_rubric(rubric.content)[0]
            for rubric in (
                self.specification_anchor,
                *(item.rubric for item in self.items),
            )
        }
        if len(protocols) != 1:
            raise ValueError("all bank members must use one scoring protocol")
        for item in self.items:
            validate_rubric_criterion_map(
                self.specification_anchor,
                item.rubric,
                item.criterion_map,
                item.elicited_criteria,
            )

    @property
    def content_sha256(self) -> str:
        """Hash the weighted bank content without round or lineage metadata."""

        members = sorted(
            (
                {
                    "content_sha256": item.rubric.content_sha256,
                    "weight_hex": item.weight.hex(),
                    "criterion_map": [
                        mapping.as_dict() for mapping in item.criterion_map
                    ],
                    "elicited_criteria": [
                        criterion.as_dict()
                        for criterion in item.elicited_criteria
                    ],
                }
                for item in self.items
            ),
            key=lambda member: member["content_sha256"],
        )
        payload = json.dumps(
            {
                "specification_anchor_sha256": (
                    self.specification_anchor.content_sha256
                ),
                "members": members,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256_text(payload)

    @property
    def rubric_count(self) -> int:
        """Return the number of complete rubrics in the bank."""

        return len(self.items)

    @property
    def scoring_protocol(self) -> str | None:
        """Return the bank-wide scoring protocol directive."""

        protocol, _ = _validate_complete_rubric(self.specification_anchor.content)
        return protocol

    @property
    def normalization_maximum(self) -> int:
        """Return the bank-wide raw score maximum that maps to 100."""

        _, maximum = _validate_complete_rubric(self.items[0].rubric.content)
        return maximum

    @property
    def inverse_weight_concentration(self) -> float:
        """Return the inverse sum of squared operational weights."""

        return 1.0 / math.fsum(item.weight**2 for item in self.items)

    def aggregate(self, scores: Mapping[str, float]) -> float:
        """Return the weighted score for one exact score per rubric hash."""

        if not isinstance(scores, Mapping):
            raise ValueError("scores must be a mapping")
        expected_hashes = {item.rubric.content_sha256 for item in self.items}
        supplied_hashes = set(scores)
        if supplied_hashes != expected_hashes:
            missing = sorted(expected_hashes - supplied_hashes)
            extra = sorted(supplied_hashes - expected_hashes)
            raise ValueError(
                f"scores must match the bank exactly; missing={missing}, extra={extra}"
            )

        weighted_scores: list[float] = []
        for item in self.items:
            score = scores[item.rubric.content_sha256]
            if isinstance(score, bool) or not isinstance(score, Real):
                raise ValueError("each rubric score must be a real number")
            numeric_score = float(score)
            if not math.isfinite(numeric_score):
                raise ValueError("each rubric score must be finite")
            weighted_scores.append(item.weight * numeric_score)
        return math.fsum(weighted_scores)

    def validate_lineage(self, prior_bank: RubricBank) -> None:
        """Validate every lineage claim against the immediately prior bank."""

        if not isinstance(prior_bank, RubricBank):
            raise ValueError("prior_bank must be a RubricBank")
        if prior_bank.generation_round != self.generation_round - 1:
            raise ValueError("prior_bank must be the immediately preceding generation")
        if self.scoring_protocol != prior_bank.scoring_protocol:
            raise ValueError(
                "a specification anchor cannot change the bank scoring protocol"
            )

        if self.prior_specification_anchor_sha256 != (
            prior_bank.specification_anchor.content_sha256
        ):
            raise ValueError("specification anchor lineage references the wrong prior hash")
        if (
            self.specification_anchor != prior_bank.specification_anchor
            or self.specification_anchor_lineage is not RubricLineage.RETAINED
        ):
            raise ValueError("the original rubric cannot change")

        prior_by_hash = {
            item.rubric.content_sha256: item for item in prior_bank.items
        }
        prior_hashes = set(prior_by_hash)
        descendant_lineages: dict[str, list[RubricLineage]] = {}
        for item in self.items:
            current_hash = item.rubric.content_sha256
            prior_hash = item.prior_content_sha256

            if item.lineage is RubricLineage.NEW:
                if current_hash in prior_hashes:
                    raise ValueError(
                        "a rubric present in the prior bank must be retained"
                    )
                continue

            assert prior_hash is not None
            if prior_hash not in prior_hashes:
                raise ValueError("a lineage reference is absent from the prior bank")
            descendant_lineages.setdefault(prior_hash, []).append(item.lineage)

            if item.lineage is RubricLineage.RETAINED:
                if current_hash != prior_hash:
                    raise ValueError("retained lineage changed the rubric content")
                if item.criterion_map != prior_by_hash[prior_hash].criterion_map:
                    raise ValueError("a retained member must keep its criterion map")
                if (
                    item.elicited_criteria
                    != prior_by_hash[prior_hash].elicited_criteria
                ):
                    raise ValueError(
                        "a retained rubric must keep its elicited criteria"
                    )
            else:
                if current_hash in prior_hashes:
                    raise ValueError(
                        "refined lineage must produce content absent from the prior bank"
                    )
                prior_criteria = prior_by_hash[prior_hash].elicited_criteria
                if (
                    item.elicited_criteria[:len(prior_criteria)] != prior_criteria
                    or len(item.elicited_criteria) <= len(prior_criteria)
                ):
                    raise ValueError(
                        "a refined rubric can only append elicited criteria"
                    )
        if any(
            len(lineages) > 1
            and any(lineage is not RubricLineage.REFINED for lineage in lineages)
            for lineages in descendant_lineages.values()
        ):
            raise ValueError(
                "multiple descendants of one prior rubric must all be refined"
            )


def canonical_rubric_bank_items(bank: RubricBank) -> tuple[RubricBankItem, ...]:
    """Return the member order used by every model-facing bank renderer."""

    if not isinstance(bank, RubricBank):
        raise ValueError("bank must be a RubricBank")
    return tuple(
        sorted(bank.items, key=lambda item: item.rubric.content_sha256)
    )


@dataclass(frozen=True)
class RubricBankGeneration:
    """Attach the predeclared proposer-call budget to one bank."""

    bank: RubricBank
    proposer_call_budget: int

    def __post_init__(self) -> None:
        if not isinstance(self.bank, RubricBank):
            raise ValueError("bank must be a RubricBank")
        _require_nonnegative_int(
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

    _require_nonnegative_int(generation_round, "generation_round")
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
        for path in stage.rglob("*"):
            make_read_only(path)
        make_read_only(stage)
        os.rename(stage, bank_dir)
        directory_fd = os.open(bank_parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if stage.exists():
            for path in sorted(stage.rglob("*"), reverse=True):
                try:
                    path.chmod(0o700 if path.is_dir() else 0o600)
                except OSError:
                    pass
            stage.chmod(0o700)
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


def _load_rubric_bank_directory(
    bank_dir: Path,
    generation_round: int,
    *,
    expected_policy: RubricBankPolicy | None,
) -> RubricBankGeneration:
    """Load one bank from its final or unpublished staged directory."""

    manifest_path = bank_dir / "manifest.json"
    if bank_dir.is_symlink() or not bank_dir.is_dir():
        raise RuntimeError(f"rubric bank directory is missing: {bank_dir}")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"rubric bank manifest is missing: {manifest_path}")
    try:
        payload = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"rubric bank manifest is invalid: {manifest_path}") from exc
    if not isinstance(payload, dict) or set(payload) != _BANK_MANIFEST_KEYS:
        raise RuntimeError("rubric bank manifest has invalid fields")
    try:
        policy = RubricBankPolicy(payload["policy"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("rubric bank manifest has an invalid policy") from exc
    if expected_policy is not None and policy is not expected_policy:
        raise RuntimeError("rubric bank manifest has the wrong policy")
    if payload.get("generation_round") != generation_round:
        raise RuntimeError("rubric bank manifest has the wrong generation round")
    members = payload.get("members")
    if not isinstance(members, list) or not members:
        raise RuntimeError("rubric bank manifest has invalid members")
    members_dir = bank_dir / "members"
    if members_dir.is_symlink() or not members_dir.is_dir():
        raise RuntimeError("rubric bank members directory is invalid")

    anchor_payload = payload.get("specification_anchor")
    if (
        not isinstance(anchor_payload, dict)
        or set(anchor_payload) != _BANK_ANCHOR_KEYS
    ):
        raise RuntimeError("rubric bank manifest has an invalid specification anchor")
    try:
        anchor_digest = _require_sha256(
            anchor_payload["content_sha256"],
            "specification_anchor.content_sha256",
        )
        anchor_relative_path = Path(anchor_payload["path"])
        if anchor_relative_path != Path("specification-anchor.txt"):
            raise ValueError("specification anchor path is not canonical")
        anchor_path = bank_dir / anchor_relative_path
        if anchor_path.is_symlink() or not anchor_path.is_file():
            raise ValueError("specification anchor rubric is missing")
        specification_anchor = CompleteRubric(
            content=anchor_path.read_text(encoding="utf-8"),
            content_sha256=anchor_digest,
        )
        specification_anchor_lineage = RubricLineage(anchor_payload["lineage"])
        prior_specification_anchor_sha256 = anchor_payload[
            "prior_content_sha256"
        ]
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "rubric bank manifest has an invalid specification anchor"
        ) from exc

    items: list[RubricBankItem] = []
    expected_paths: set[Path] = {manifest_path, anchor_path}
    for member in members:
        if not isinstance(member, dict) or set(member) != _BANK_MEMBER_KEYS:
            raise RuntimeError("rubric bank manifest has an invalid member")
        try:
            digest = _require_sha256(member["content_sha256"], "content_sha256")
            relative_path = Path(member["path"])
            if (
                relative_path != Path("members") / f"{digest}.txt"
                or relative_path.is_absolute()
                or ".." in relative_path.parts
            ):
                raise ValueError("member path is not canonical")
            member_path = bank_dir / relative_path
            if member_path.is_symlink() or not member_path.is_file():
                raise ValueError("member rubric is missing")
            rubric = CompleteRubric(
                content=member_path.read_text(encoding="utf-8"),
                content_sha256=digest,
            )
            criterion_map_payload = member["criterion_map"]
            if not isinstance(criterion_map_payload, list):
                raise ValueError("member criterion map is invalid")
            criterion_map: list[RubricCriterionMapping] = []
            for mapping in criterion_map_payload:
                if (
                    not isinstance(mapping, dict)
                    or set(mapping) != _CRITERION_MAPPING_KEYS
                ):
                    raise ValueError("member criterion mapping is invalid")
                criterion_map.append(RubricCriterionMapping(
                    anchor_criterion_id=mapping["anchor_criterion_id"],
                    member_criterion_id=mapping["member_criterion_id"],
                ))
            elicited_payload = member["elicited_criteria"]
            if not isinstance(elicited_payload, list):
                raise ValueError("member elicited criteria are invalid")
            item = RubricBankItem(
                rubric=rubric,
                weight=member["weight"],
                lineage=RubricLineage(member["lineage"]),
                criterion_map=tuple(criterion_map),
                prior_content_sha256=member["prior_content_sha256"],
                elicited_criteria=tuple(
                    parse_elicited_criterion(value)
                    for value in elicited_payload
                ),
            )
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            raise RuntimeError("rubric bank manifest has an invalid member") from exc
        items.append(item)
        expected_paths.add(member_path)

    expected_directories = {members_dir}
    actual_entries = set(bank_dir.rglob("*"))
    if actual_entries != expected_paths | expected_directories:
        raise RuntimeError("rubric bank directory contains unexpected files")
    try:
        bank = RubricBank(
            generation_round=generation_round,
            source_boundary=payload["source_boundary"],
            specification_anchor=specification_anchor,
            specification_anchor_lineage=specification_anchor_lineage,
            prior_specification_anchor_sha256=prior_specification_anchor_sha256,
            items=tuple(items),
        )
        generation = RubricBankGeneration(
            bank=bank,
            proposer_call_budget=payload["proposer_call_budget"],
        )
        _validate_policy_bank(policy, bank)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("rubric bank manifest has invalid values") from exc
    if payload.get("bank_sha256") != bank.content_sha256:
        raise RuntimeError("rubric bank manifest has the wrong bank hash")
    if (
        type(payload.get("rubric_count")) is not int
        or payload["rubric_count"] != bank.rubric_count
        or isinstance(payload.get("inverse_weight_concentration"), bool)
        or not isinstance(payload.get("inverse_weight_concentration"), Real)
        or not math.isfinite(float(payload["inverse_weight_concentration"]))
        or float(payload["inverse_weight_concentration"])
        != bank.inverse_weight_concentration
    ):
        raise RuntimeError("rubric bank manifest has invalid derived statistics")
    return generation


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value
