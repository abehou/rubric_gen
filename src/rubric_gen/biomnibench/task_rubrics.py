"""Structured task-rubric schema, parsing, validation, and snapshot models."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.biomnibench.rubric_scoring import parse_rubric_levels_strict


def canonical_json(value: object) -> str:
    """Serialize JSON with one stable, whitespace-free representation."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_text(value: str) -> str:
    """Return the lowercase SHA-256 digest of UTF-8 text."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SchemaSnapshotLimits:
    max_files: int = 16
    max_entries_visited: int = 256
    max_probe_bytes: int = 65_536
    max_rows: int = 20
    max_columns: int = 32
    max_examples_per_column: int = 3
    max_string_chars: int = 120
    max_output_chars: int = 12_000

    def __post_init__(self) -> None:
        for field_name in (
            "max_files",
            "max_entries_visited",
            "max_probe_bytes",
            "max_rows",
            "max_columns",
            "max_examples_per_column",
            "max_string_chars",
            "max_output_chars",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.max_output_chars < len("[]"):
            raise ValueError("max_output_chars must be at least 2")


@dataclass(frozen=True)
class _ImmutableFileSnapshot:
    size_bytes: int
    sha256: str
    captured_bytes: bytes


@dataclass(frozen=True)
class DataFileSnapshot:
    path: str
    size_bytes: int
    sha256: str
    kind: str
    delimiter: str | None = None
    rows_seen: int = 0
    columns: tuple[str, ...] = ()
    column_types: tuple[str, ...] = ()
    examples: tuple[tuple[str, ...], ...] = ()
    probe_bytes: int = 0
    probe_truncated: bool = False
    omitted_rows: int = 0
    omitted_columns: int = 0
    omitted_examples: int = 0

    def to_dict(self) -> dict[str, object]:
        if self.kind == "binary":
            return {
                "kind": self.kind,
                "path": self.path,
                "sha256": self.sha256,
                "size_bytes": self.size_bytes,
            }
        return {
            "column_types": list(self.column_types),
            "columns": list(self.columns),
            "delimiter": self.delimiter,
            "examples": [list(values) for values in self.examples],
            "kind": self.kind,
            "omitted_columns": self.omitted_columns,
            "omitted_examples": self.omitted_examples,
            "omitted_rows": self.omitted_rows,
            "path": self.path,
            "probe_bytes": self.probe_bytes,
            "probe_truncated": self.probe_truncated,
            "rows_seen": self.rows_seen,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class TaskAnchor:
    anchor_id: str
    kind: str
    text: str
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "anchor_id": self.anchor_id,
            "kind": self.kind,
            "source": self.source,
            "text": self.text,
        }


@dataclass(frozen=True)
class TaskSnapshot:
    schema_version: int
    task_id: str
    question: str
    required_outputs: tuple[str, ...]
    data_files: tuple[DataFileSnapshot, ...]
    anchors: tuple[TaskAnchor, ...]
    required_summary_anchor_ids: tuple[str, ...]
    input_hashes: tuple[tuple[str, str], ...]
    snapshot_sha256: str
    omitted_data_files: int = 0
    data_traversal_truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "anchors": [anchor.to_dict() for anchor in self.anchors],
            "data_files": [data_file.to_dict() for data_file in self.data_files],
            "data_traversal_truncated": self.data_traversal_truncated,
            "input_hashes": [list(item) for item in self.input_hashes],
            "omitted_data_files": self.omitted_data_files,
            "question": self.question,
            "required_outputs": list(self.required_outputs),
            "required_summary_anchor_ids": list(self.required_summary_anchor_ids),
            "schema_version": self.schema_version,
            "snapshot_sha256": self.snapshot_sha256,
            "task_id": self.task_id,
        }


@dataclass(frozen=True)
class RubricLevel:
    label: str
    points: int
    description: str


@dataclass(frozen=True)
class RubricCriterion:
    criterion_id: str
    title: str
    description: str
    max_points: int
    task_anchors: tuple[str, ...]
    required_evidence: tuple[str, ...]
    acceptable_alternatives: tuple[str, ...]
    anti_evidence: tuple[str, ...]
    verification: tuple[str, ...]
    levels: tuple[RubricLevel, ...]


@dataclass(frozen=True)
class TaskProcessRubric:
    schema_version: int
    task_id: str
    purpose: str
    criteria: tuple[RubricCriterion, ...]


_RUBRIC_KEYS = ("schema_version", "task_id", "purpose", "criteria")
_CRITERION_KEYS = (
    "criterion_id",
    "title",
    "description",
    "max_points",
    "task_anchors",
    "required_evidence",
    "acceptable_alternatives",
    "anti_evidence",
    "verification",
    "levels",
)
_LEVEL_KEYS = ("label", "points", "description")
_EVIDENCE_FIELDS = (
    "required_evidence",
    "acceptable_alternatives",
    "anti_evidence",
    "verification",
)
_ASCII_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_SEARCH_IDENTIFIER = r"(?:run|candidate|condition)[\s_-]+ids?"
_RUNTIME_CONTEXT_PATTERNS = (
    (
        "search/optimization identifier",
        re.compile(
            rf"\b(?:current[\s_-]+search|hill[\s_-]*climb(?:ing)?|"
            rf"self[\s_-]*improv(?:ement|ing)|reward[\s_-]+optim(?:ization|isation)|"
            rf"optimizer|runtime)(?:[\s_-]+\w+){{0,3}}[\s_-]+"
            rf"{_SEARCH_IDENTIFIER}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "score-conditioned identifier",
        re.compile(
            rf"\b{_SEARCH_IDENTIFIER}\b[^.!?\n]{{0,48}}\b"
            rf"(?:used[\s_-]+for|used[\s_-]+to[\s_-]+"
            rf"(?:award|assign|determine)|determines?|controls?)"
            rf"[\s_-]+(?:credit|scores?|scoring|acceptance)\b",
            re.IGNORECASE,
        ),
    ),
    ("search history", re.compile(r"\bsearch[\s_-]+history\b", re.IGNORECASE)),
    (
        "prior/previous score",
        re.compile(r"\b(?:prior|previous)[\s_-]+scores?\b", re.IGNORECASE),
    ),
    (
        "accepted/rejected/parent candidate",
        re.compile(
            r"\b(?:accepted|rejected|parent)[\s_-]+candidates?\b",
            re.IGNORECASE,
        ),
    ),
    ("hidden audit", re.compile(r"\bhidden[\s_-]+audit\b", re.IGNORECASE)),
    (
        "criterion feedback",
        re.compile(r"\bcriterion[\s_-]+feedback\b", re.IGNORECASE),
    ),
)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def load_json_strict(text: str) -> object:
    """Decode JSON while rejecting duplicate keys and non-standard constants."""

    if type(text) is not str:
        raise ValueError("JSON input must be a string")
    return json.loads(
        text,
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )


def _closed_object(
    value: object,
    keys: tuple[str, ...],
    context: str,
) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError(f"{context} must be an object")
    unexpected = sorted(set(value) - set(keys))
    if unexpected:
        raise ValueError(f"{context} has unexpected key: {unexpected[0]}")
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValueError(f"{context} is missing key: {missing[0]}")
    return value


def _strict_value(
    value: object,
    expected_type: type[object],
    context: str,
) -> object:
    if type(value) is not expected_type:
        type_name = "integer" if expected_type is int else expected_type.__name__
        raise ValueError(f"{context} must be an {type_name}")
    return value


def _string_list(value: object, context: str) -> tuple[str, ...]:
    _strict_value(value, list, context)
    items: list[str] = []
    for index, item in enumerate(value):
        _strict_value(item, str, f"{context}[{index}]")
        items.append(item)
    return tuple(items)


def parse_task_process_rubric(response: str) -> TaskProcessRubric:
    """Parse strict schema-version-1 JSON without type coercion."""

    _strict_value(response, str, "rubric response")
    raw = load_json_strict(response)
    payload = _closed_object(raw, _RUBRIC_KEYS, "rubric")
    schema_version = _strict_value(
        payload["schema_version"],
        int,
        "schema_version",
    )
    task_id = _strict_value(payload["task_id"], str, "task_id")
    purpose = _strict_value(payload["purpose"], str, "purpose")
    raw_criteria = _strict_value(payload["criteria"], list, "criteria")
    criteria: list[RubricCriterion] = []
    for criterion_index, raw_criterion in enumerate(raw_criteria):
        context = f"criteria[{criterion_index}]"
        criterion = _closed_object(raw_criterion, _CRITERION_KEYS, context)
        raw_levels = _strict_value(criterion["levels"], list, f"{context}.levels")
        levels: list[RubricLevel] = []
        for level_index, raw_level in enumerate(raw_levels):
            level_context = f"{context}.levels[{level_index}]"
            level = _closed_object(raw_level, _LEVEL_KEYS, level_context)
            levels.append(
                RubricLevel(
                    label=_strict_value(level["label"], str, f"{level_context}.label"),
                    points=_strict_value(
                        level["points"], int, f"{level_context}.points"
                    ),
                    description=_strict_value(
                        level["description"],
                        str,
                        f"{level_context}.description",
                    ),
                )
            )
        criteria.append(
            RubricCriterion(
                criterion_id=_strict_value(
                    criterion["criterion_id"],
                    str,
                    f"{context}.criterion_id",
                ),
                title=_strict_value(criterion["title"], str, f"{context}.title"),
                description=_strict_value(
                    criterion["description"],
                    str,
                    f"{context}.description",
                ),
                max_points=_strict_value(
                    criterion["max_points"],
                    int,
                    f"{context}.max_points",
                ),
                task_anchors=_string_list(
                    criterion["task_anchors"],
                    f"{context}.task_anchors",
                ),
                required_evidence=_string_list(
                    criterion["required_evidence"],
                    f"{context}.required_evidence",
                ),
                acceptable_alternatives=_string_list(
                    criterion["acceptable_alternatives"],
                    f"{context}.acceptable_alternatives",
                ),
                anti_evidence=_string_list(
                    criterion["anti_evidence"],
                    f"{context}.anti_evidence",
                ),
                verification=_string_list(
                    criterion["verification"],
                    f"{context}.verification",
                ),
                levels=tuple(levels),
            )
        )
    return TaskProcessRubric(
        schema_version=schema_version,
        task_id=task_id,
        purpose=purpose,
        criteria=tuple(criteria),
    )


def _validate_nonempty_unique_items(
    criterion_id: str,
    field_name: str,
    values: tuple[str, ...],
) -> tuple[str, ...]:
    errors: list[str] = []
    if not values:
        errors.append(f"{criterion_id}: {field_name} must be non-empty")
        return tuple(errors)
    normalized = [value.strip() for value in values]
    if any(not value for value in normalized):
        errors.append(f"{criterion_id}: {field_name} contains an empty item")
    if len(set(normalized)) != len(normalized):
        errors.append(f"{criterion_id}: {field_name} contains duplicate items")
    return tuple(errors)


def _ascii_control_error(context: str, value: str) -> str | None:
    if _ASCII_CONTROL_PATTERN.search(value) is not None:
        return f"{context} must not contain ASCII control characters"
    return None


def _rubric_authored_prose(
    rubric: TaskProcessRubric,
) -> tuple[tuple[str, str], ...]:
    """Return free-form prose; closed structural identifiers validate separately."""

    authored = [("purpose", rubric.purpose)]
    for criterion in rubric.criteria:
        authored.extend(
            (
                (f"{criterion.criterion_id}: title", criterion.title),
                (f"{criterion.criterion_id}: description", criterion.description),
            )
        )
        for field_name in _EVIDENCE_FIELDS:
            authored.extend(
                (f"{criterion.criterion_id}: {field_name}", value)
                for value in getattr(criterion, field_name)
            )
        authored.extend(
            (
                f"{criterion.criterion_id} level {level.label}: description",
                level.description,
            )
            for level in criterion.levels
        )
    return tuple(authored)


def _runtime_context_errors(
    rubric: TaskProcessRubric,
) -> tuple[str, ...]:
    errors: list[str] = []
    for context, value in _rubric_authored_prose(rubric):
        for phrase_name, pattern in _RUNTIME_CONTEXT_PATTERNS:
            if pattern.search(value) is not None:
                errors.append(
                    f"{context} must not refer to runtime/search context "
                    f"({phrase_name})"
                )
    return tuple(errors)


def validate_task_process_rubric(
    rubric: TaskProcessRubric,
    snapshot: TaskSnapshot,
) -> tuple[str, ...]:
    """Return every deterministic schema and task-grounding error."""

    errors: list[str] = []
    if rubric.schema_version != 1:
        errors.append("schema_version must be 1")
    if rubric.task_id != snapshot.task_id:
        errors.append("task_id does not match snapshot")
    if not rubric.purpose.strip():
        errors.append("purpose must be non-empty")
    purpose_control_error = _ascii_control_error("purpose", rubric.purpose)
    if purpose_control_error is not None:
        errors.append(purpose_control_error)
    if not rubric.criteria:
        errors.append("criteria must be non-empty")
    errors.extend(_runtime_context_errors(rubric))

    known_anchors = {anchor.anchor_id for anchor in snapshot.anchors}
    covered_anchors: set[str] = set()
    for index, criterion in enumerate(rubric.criteria, start=1):
        criterion_name = criterion.criterion_id or f"criterion {index}"
        if criterion.criterion_id != f"C{index}":
            errors.append("criterion IDs must be contiguous C1..Cn")
        if not criterion.title.strip():
            errors.append(f"{criterion_name}: title must be non-empty")
        title_control_error = _ascii_control_error(
            f"{criterion_name}: title",
            criterion.title,
        )
        if title_control_error is not None:
            errors.append(title_control_error)
        if not criterion.description.strip():
            errors.append(f"{criterion_name}: description must be non-empty")
        description_control_error = _ascii_control_error(
            f"{criterion_name}: description",
            criterion.description,
        )
        if description_control_error is not None:
            errors.append(description_control_error)

        if not criterion.task_anchors:
            errors.append(f"{criterion_name}: task_anchors must be non-empty")
        if len(set(criterion.task_anchors)) != len(criterion.task_anchors):
            errors.append(f"{criterion_name}: duplicate task anchor")
        for anchor_id in criterion.task_anchors:
            anchor_control_error = _ascii_control_error(
                f"{criterion_name}: task_anchors",
                anchor_id,
            )
            if anchor_control_error is not None:
                errors.append(anchor_control_error)
            if anchor_id not in known_anchors:
                errors.append(f"{criterion_name}: unknown task anchor {anchor_id}")
            else:
                covered_anchors.add(anchor_id)

        for field_name in _EVIDENCE_FIELDS:
            for value in getattr(criterion, field_name):
                field_control_error = _ascii_control_error(
                    f"{criterion_name}: {field_name}",
                    value,
                )
                if field_control_error is not None:
                    errors.append(field_control_error)
            errors.extend(
                _validate_nonempty_unique_items(
                    criterion_name,
                    field_name,
                    getattr(criterion, field_name),
                )
            )

        if len(criterion.levels) < 3:
            errors.append(f"{criterion_name}: must have at least three levels")
        if len(criterion.levels) > 26:
            errors.append(f"{criterion_name}: must have at most 26 levels")
        if any(
            re.fullmatch(r"[A-Z]", level.label) is None for level in criterion.levels
        ):
            errors.append(f"{criterion_name}: level labels must use A through Z")
        expected_labels = tuple(
            chr(ord("A") + level_index) for level_index in range(len(criterion.levels))
        )
        actual_labels = tuple(level.label for level in criterion.levels)
        if actual_labels != expected_labels:
            errors.append(f"{criterion_name}: level labels must be contiguous from A")
        points = tuple(level.points for level in criterion.levels)
        if any(left <= right for left, right in zip(points, points[1:])):
            errors.append(f"{criterion_name}: level points must be strictly descending")
        if points.count(0) != 1:
            errors.append(f"{criterion_name}: must have exactly one zero-point level")
        if points and points[0] != criterion.max_points:
            errors.append(f"{criterion_name}: A-level points must equal max_points")
        for level in criterion.levels:
            if not level.description.strip():
                errors.append(
                    f"{criterion_name} level {level.label}: description must be non-empty"
                )
            level_control_error = _ascii_control_error(
                f"{criterion_name} level {level.label}: description",
                level.description,
            )
            if level_control_error is not None:
                errors.append(level_control_error)

    for anchor_id in snapshot.required_summary_anchor_ids:
        if anchor_id not in covered_anchors:
            errors.append(f"required summary anchor is not covered: {anchor_id}")
    if sum(criterion.max_points for criterion in rubric.criteria) != 100:
        errors.append("total max_points must equal 100")
    return tuple(errors)


def _render_items(lines: list[str], heading: str, items: tuple[str, ...]) -> None:
    lines.append(f"    {heading}:")
    lines.extend(f"      - {item}" for item in items)


def render_task_process_rubric(rubric: TaskProcessRubric) -> str:
    """Render one stable judge-facing rubric text representation."""

    lines = [f"Purpose: {rubric.purpose}"]
    for index, criterion in enumerate(rubric.criteria, start=1):
        lines.extend(("", f"Criterion {index}: {criterion.title}", ""))
        lines.append(f"    Description: {criterion.description}")
        _render_items(lines, "Task anchors", criterion.task_anchors)
        _render_items(lines, "Required evidence", criterion.required_evidence)
        _render_items(
            lines, "Acceptable alternatives", criterion.acceptable_alternatives
        )
        _render_items(lines, "Anti-evidence", criterion.anti_evidence)
        _render_items(lines, "Verification", criterion.verification)
        rendered_levels = " ".join(
            f"{level.label}={level.points}" for level in criterion.levels
        )
        lines.append(f"    Levels: {rendered_levels}")
        lines.extend(
            f"      [{level.label}]: {level.description}" for level in criterion.levels
        )
    return "\n".join(lines) + "\n"


def structured_rubric_level_map(
    rubric: TaskProcessRubric,
) -> dict[str, dict[str, int]]:
    """Return the scoring map implied by one structured rubric."""

    return {
        f"criterion_{index}": {level.label: level.points for level in criterion.levels}
        for index, criterion in enumerate(rubric.criteria, start=1)
    }


def validate_rendered_task_process_rubric(
    rubric: TaskProcessRubric,
    rendered: str,
) -> None:
    """Require rendered scoring structure to round-trip to the structured rubric."""

    rendered_strings = [("purpose", rubric.purpose)]
    for criterion in rubric.criteria:
        rendered_strings.extend(
            (
                (f"{criterion.criterion_id}: title", criterion.title),
                (f"{criterion.criterion_id}: description", criterion.description),
            )
        )
        for field_name in ("task_anchors", *_EVIDENCE_FIELDS):
            rendered_strings.extend(
                (f"{criterion.criterion_id}: {field_name}", value)
                for value in getattr(criterion, field_name)
            )
        rendered_strings.extend(
            (
                f"{criterion.criterion_id} level {level.label}: description",
                level.description,
            )
            for level in criterion.levels
        )
    for context, value in rendered_strings:
        control_error = _ascii_control_error(context, value)
        if control_error is not None:
            raise ValueError(control_error)
    runtime_errors = _runtime_context_errors(rubric)
    if runtime_errors:
        raise ValueError(runtime_errors[0])

    parsed = parse_rubric_levels_strict(rendered)
    if parsed != structured_rubric_level_map(rubric):
        raise ValueError(
            "rendered rubric criterion/level map does not match structured rubric"
        )


def build_task_snapshot(
    task_dir: Path,
    limits: SchemaSnapshotLimits = SchemaSnapshotLimits(),
) -> TaskSnapshot:
    """Build a deterministic snapshot without consulting runtime files."""

    from rubric_gen.biomnibench.task_snapshots import (
        build_task_snapshot as build_snapshot,
    )

    return build_snapshot(task_dir, limits)
