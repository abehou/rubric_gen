"""Rubric-generation domain models, rendering, and lineage validation."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.autorubric import (
    AutoRubricAdapterError,
    parse_autorubric_rubric,
)


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
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


def require_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def require_sha256(value: object, field_name: str) -> str:
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


class RubricPolicy(str, Enum):
    """Define how an experiment changes its active rubric."""

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
        require_sha256(self.content_sha256, "content_sha256")
        if sha256_text(self.content) != self.content_sha256:
            raise ValueError("content_sha256 does not match rubric content")
        _validate_complete_rubric(self.content)

    @classmethod
    def from_content(cls, content: str) -> CompleteRubric:
        """Create a rubric with the hash of its exact UTF-8 content."""

        if type(content) is not str:
            raise ValueError("rubric content must be a string")
        return cls(content=content, content_sha256=sha256_text(content))


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
        require_nonnegative_int(self.source_generation, "source_generation")
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
) -> CompleteRubric:
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
        return original_rubric

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
    for index, criterion in enumerate(parsed.criteria, start=1):
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
    return CompleteRubric.from_content("\n".join(lines).rstrip() + "\n")


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


@dataclass(frozen=True)
class RubricGeneration:
    """Store one complete active rubric and its cumulative elicited criteria."""

    generation_round: int
    source_boundary: int | None
    rubric: CompleteRubric
    elicited_criteria: tuple[ElicitedCriterion, ...]
    proposer_call_budget: int

    def __post_init__(self) -> None:
        generation_round = require_nonnegative_int(
            self.generation_round,
            "generation_round",
        )
        require_nonnegative_int(self.proposer_call_budget, "proposer_call_budget")
        if self.source_boundary is not None:
            source_boundary = require_nonnegative_int(
                self.source_boundary,
                "source_boundary",
            )
            if source_boundary != generation_round:
                raise ValueError(
                    "source_boundary must equal the rubric generation round"
                )
        if generation_round == 0 and self.source_boundary is not None:
            raise ValueError("the initial rubric cannot have a source boundary")
        if not isinstance(self.rubric, CompleteRubric):
            raise ValueError("rubric must be a CompleteRubric")
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
        if generation_round == 0 and self.elicited_criteria:
            raise ValueError("the initial rubric cannot contain elicited criteria")
        if any(
            criterion.source_generation > generation_round
            for criterion in self.elicited_criteria
        ):
            raise ValueError("elicited criterion comes from a later generation")

    @property
    def generation_sha256(self) -> str:
        """Return the identity of the complete generation content."""

        payload = json.dumps(
            {
                "generation_round": self.generation_round,
                "source_boundary": self.source_boundary,
                "rubric_sha256": self.rubric.content_sha256,
                "elicited_criteria": [
                    criterion.as_dict() for criterion in self.elicited_criteria
                ],
                "proposer_call_budget": self.proposer_call_budget,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return sha256_text(payload)

    @property
    def scoring_protocol(self) -> str | None:
        protocol, _ = _validate_complete_rubric(self.rubric.content)
        return protocol

    @property
    def normalization_maximum(self) -> int:
        _, maximum = _validate_complete_rubric(self.rubric.content)
        return maximum

    def validate_successor(self, prior: RubricGeneration) -> None:
        """Require consecutive generation identity and append-only criteria."""

        if not isinstance(prior, RubricGeneration):
            raise ValueError("prior must be a RubricGeneration")
        if self.generation_round != prior.generation_round + 1:
            raise ValueError("rubric generations must be consecutive")
        if self.scoring_protocol != prior.scoring_protocol:
            raise ValueError("a rubric generation cannot change scoring protocol")
        prior_count = len(prior.elicited_criteria)
        if self.elicited_criteria[:prior_count] != prior.elicited_criteria:
            raise ValueError("a rubric generation cannot change prior criteria")
