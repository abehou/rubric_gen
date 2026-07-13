"""Deterministic snapshots of immutable BiomniBench task inputs."""

from __future__ import annotations

import codecs
import csv
import hashlib
import heapq
import io
import json
import re
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path


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


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


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
    raw = json.loads(
        response,
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )
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
            levels.append(RubricLevel(
                label=_strict_value(level["label"], str, f"{level_context}.label"),
                points=_strict_value(level["points"], int, f"{level_context}.points"),
                description=_strict_value(
                    level["description"],
                    str,
                    f"{level_context}.description",
                ),
            ))
        criteria.append(RubricCriterion(
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
        ))
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
    if not rubric.criteria:
        errors.append("criteria must be non-empty")

    known_anchors = {anchor.anchor_id for anchor in snapshot.anchors}
    covered_anchors: set[str] = set()
    for index, criterion in enumerate(rubric.criteria, start=1):
        criterion_name = criterion.criterion_id or f"criterion {index}"
        if criterion.criterion_id != f"C{index}":
            errors.append("criterion IDs must be contiguous C1..Cn")
        if not criterion.title.strip():
            errors.append(f"{criterion_name}: title must be non-empty")
        if not criterion.description.strip():
            errors.append(f"{criterion_name}: description must be non-empty")

        if not criterion.task_anchors:
            errors.append(f"{criterion_name}: task_anchors must be non-empty")
        if len(set(criterion.task_anchors)) != len(criterion.task_anchors):
            errors.append(f"{criterion_name}: duplicate task anchor")
        for anchor_id in criterion.task_anchors:
            if anchor_id not in known_anchors:
                errors.append(f"{criterion_name}: unknown task anchor {anchor_id}")
            else:
                covered_anchors.add(anchor_id)

        for field_name in _EVIDENCE_FIELDS:
            errors.extend(_validate_nonempty_unique_items(
                criterion_name,
                field_name,
                getattr(criterion, field_name),
            ))

        if len(criterion.levels) < 3:
            errors.append(f"{criterion_name}: must have at least three levels")
        expected_labels = tuple(
            chr(ord("A") + level_index)
            for level_index in range(len(criterion.levels))
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
        _render_items(lines, "Acceptable alternatives", criterion.acceptable_alternatives)
        _render_items(lines, "Anti-evidence", criterion.anti_evidence)
        _render_items(lines, "Verification", criterion.verification)
        rendered_levels = " ".join(
            f"{level.label}={level.points}" for level in criterion.levels
        )
        lines.append(f"    Levels: {rendered_levels}")
        lines.extend(
            f"      [{level.label}]: {level.description}"
            for level in criterion.levels
        )
    return "\n".join(lines) + "\n"


def _snapshot_payload(snapshot: TaskSnapshot) -> dict[str, object]:
    payload = snapshot.to_dict()
    payload.pop("snapshot_sha256")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _infer_column_type(values: list[str]) -> str:
    nonempty = [value for value in values if value != ""]
    if not nonempty:
        return "empty"
    lowered = [value.lower() for value in nonempty]
    if all(value in {"true", "false", "yes", "no"} for value in lowered):
        return "boolean"
    try:
        for value in nonempty:
            int(value)
        return "integer"
    except ValueError:
        pass
    try:
        for value in nonempty:
            float(value)
        return "number"
    except ValueError:
        return "string"


def _table_snapshot(
    path: Path,
    relative_path: str,
    limits: SchemaSnapshotLimits,
) -> DataFileSnapshot:
    with path.open("rb") as stream:
        probe = stream.read(limits.max_probe_bytes + 1)
    probe_truncated = len(probe) > limits.max_probe_bytes
    probe = probe[: limits.max_probe_bytes]
    common = {
        "path": relative_path,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "probe_bytes": len(probe),
        "probe_truncated": probe_truncated,
    }
    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        text = decoder.decode(probe, final=not probe_truncated)
    except UnicodeDecodeError:
        return DataFileSnapshot(kind="binary", **common)

    header_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = next(
        (candidate for candidate in ("\t", ",", ";", "|") if candidate in header_line),
        None,
    )
    if delimiter is None:
        return DataFileSnapshot(kind="text", **common)

    parsed_rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    if not parsed_rows:
        return DataFileSnapshot(kind="text", **common)
    raw_columns = parsed_rows[0]
    rows = parsed_rows[1:]
    kept_columns = [
        column[: limits.max_string_chars]
        for column in raw_columns[: limits.max_columns]
    ]
    inspected_rows = rows[: limits.max_rows]
    column_values = [
        [row[index] if index < len(row) else "" for row in inspected_rows]
        for index in range(len(kept_columns))
    ]
    examples: list[tuple[str, ...]] = []
    omitted_examples = 0
    for values in column_values:
        unique_values: list[str] = []
        for value in values:
            value = value[: limits.max_string_chars]
            if value not in unique_values:
                unique_values.append(value)
        examples.append(tuple(unique_values[: limits.max_examples_per_column]))
        omitted_examples += max(0, len(unique_values) - limits.max_examples_per_column)
    return DataFileSnapshot(
        kind="table",
        delimiter=delimiter,
        rows_seen=len(rows),
        columns=tuple(kept_columns),
        column_types=tuple(_infer_column_type(values) for values in column_values),
        examples=tuple(examples),
        omitted_rows=max(0, len(rows) - limits.max_rows),
        omitted_columns=max(0, len(raw_columns) - limits.max_columns),
        omitted_examples=omitted_examples,
        **common,
    )


def _walk_data_files(
    data_root: Path,
    limits: SchemaSnapshotLimits,
) -> tuple[tuple[Path, ...], int, bool]:
    if not data_root.is_dir():
        return (), 0, False
    pending = [("", data_root)]
    files: list[Path] = []
    omitted_files = 0
    entries_enumerated = 0
    traversal_truncated = False
    while pending:
        _, path = heapq.heappop(pending)
        if path.is_symlink():
            continue
        if path.is_dir():
            remaining = limits.max_entries_visited - entries_enumerated
            children = list(islice(path.iterdir(), remaining))
            entries_enumerated += len(children)
            if len(children) == remaining:
                traversal_truncated = True
                continue
            for child in sorted(
                children,
                key=lambda item: item.relative_to(data_root).as_posix(),
            ):
                relative = child.relative_to(data_root).as_posix()
                heapq.heappush(pending, (relative, child))
        elif path.is_file():
            if len(files) < limits.max_files:
                files.append(path)
            else:
                omitted_files += 1
    return tuple(files), omitted_files, traversal_truncated


def _schema_json(data_files: list[DataFileSnapshot]) -> str:
    return canonical_json([data_file.to_dict() for data_file in data_files])


def _fit_schema_budget(
    data_files: tuple[DataFileSnapshot, ...],
    max_output_chars: int,
) -> tuple[tuple[DataFileSnapshot, ...], int]:
    if max_output_chars < len("[]"):
        raise ValueError("max_output_chars must be at least 2")
    fitted = list(data_files)
    while len(_schema_json(fitted)) > max_output_chars:
        changed = False
        for file_index in range(len(fitted) - 1, -1, -1):
            data_file = fitted[file_index]
            for column_index in range(len(data_file.examples) - 1, -1, -1):
                values = data_file.examples[column_index]
                if not values:
                    continue
                examples = list(data_file.examples)
                examples[column_index] = values[:-1]
                fitted[file_index] = replace(
                    data_file,
                    examples=tuple(examples),
                    omitted_examples=data_file.omitted_examples + 1,
                )
                changed = True
                break
            if changed:
                break
        if not changed:
            break

    while len(_schema_json(fitted)) > max_output_chars:
        changed = False
        for file_index in range(len(fitted) - 1, -1, -1):
            data_file = fitted[file_index]
            if not data_file.columns:
                continue
            fitted[file_index] = replace(
                data_file,
                columns=data_file.columns[:-1],
                column_types=data_file.column_types[:-1],
                examples=data_file.examples[:-1],
                omitted_columns=data_file.omitted_columns + 1,
            )
            changed = True
            break
        if not changed:
            break

    omitted_files = 0
    while fitted and len(_schema_json(fitted)) > max_output_chars:
        fitted.pop()
        omitted_files += 1
    return tuple(fitted), omitted_files


def _extract_markdown_section(text: str, heading: str) -> str:
    match = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.MULTILINE)
    if match is None:
        return ""
    next_heading = re.search(r"^##\s+", text[match.end():], flags=re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end():end].strip()


def _extract_required_outputs(instruction: str) -> tuple[str, ...]:
    section = _extract_markdown_section(instruction, "Required Outputs")
    candidates = re.findall(
        r"(?:/app/)?[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}",
        section,
    )
    runtime_outputs = {"answer.txt", "trace.md"}
    outputs: list[str] = []
    for candidate in candidates:
        name = Path(candidate).name
        if name not in runtime_outputs and name not in outputs:
            outputs.append(name)
    return tuple(outputs)


def _summary_anchors(rubric: str) -> tuple[TaskAnchor, ...]:
    matches = list(re.finditer(r"^Criterion\s+(\d+)\s*:\s*(.+?)\s*$", rubric, re.MULTILINE))
    anchors: list[TaskAnchor] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(rubric)
        block = rubric[match.start():end].strip()
        anchors.append(TaskAnchor(
            anchor_id=f"summary:C{int(match.group(1))}",
            kind="summary-criterion",
            text=block,
            source="tests/rubric.txt",
        ))
    return tuple(anchors)


def _task_anchors(
    question: str,
    required_outputs: tuple[str, ...],
    summary_anchors: tuple[TaskAnchor, ...],
    data_files: tuple[DataFileSnapshot, ...],
) -> tuple[TaskAnchor, ...]:
    anchors = [TaskAnchor("task:question", "question", question, "instruction.md")]
    anchors.extend(
        TaskAnchor(
            f"task:required-output:{name}",
            "required-output",
            name,
            "instruction.md",
        )
        for name in required_outputs
    )
    anchors.extend(summary_anchors)
    for data_file in data_files:
        source = f"environment/data/{data_file.path}"
        anchors.append(TaskAnchor(
            f"data:{data_file.path}",
            "data-file",
            data_file.path,
            source,
        ))
        anchors.extend(
            TaskAnchor(
                f"schema:{data_file.path}#{column}",
                "schema-column",
                f"{column}: {column_type}",
                source,
            )
            for column, column_type in zip(data_file.columns, data_file.column_types)
        )
    anchors.extend(
        TaskAnchor(anchor_id, "evidence", text, "evidence-schema")
        for anchor_id, text in (
            ("evidence:events", "tool and lifecycle events"),
            ("evidence:commands", "executed commands"),
            ("evidence:file-reads", "file-read events"),
            ("evidence:file-writes", "file-write events"),
            ("evidence:artifacts", "produced artifacts"),
            ("evidence:final-claims", "claims in the final response"),
        )
    )
    return tuple(anchors)


def build_task_snapshot(
    task_dir: Path,
    limits: SchemaSnapshotLimits = SchemaSnapshotLimits(),
) -> TaskSnapshot:
    """Build a deterministic snapshot without consulting runtime files."""

    data_root = task_dir / "environment" / "data"
    data_paths, walk_omitted_files, traversal_truncated = _walk_data_files(data_root, limits)
    probed_data_files = tuple(
        _table_snapshot(path, path.relative_to(data_root).as_posix(), limits)
        for path in data_paths
    )
    data_files, budget_omitted_files = _fit_schema_budget(
        probed_data_files,
        limits.max_output_chars,
    )
    instruction_path = task_dir / "instruction.md"
    rubric_path = task_dir / "tests" / "rubric.txt"
    instruction = instruction_path.read_text(encoding="utf-8")
    rubric = rubric_path.read_text(encoding="utf-8")
    question = " ".join(_extract_markdown_section(instruction, "Question").split())
    required_outputs = _extract_required_outputs(instruction)
    summary_anchors = _summary_anchors(rubric)
    anchors = _task_anchors(question, required_outputs, summary_anchors, data_files)
    immutable_paths = [instruction_path, rubric_path]
    task_config_path = task_dir / "task.toml"
    if task_config_path.is_file() and not task_config_path.is_symlink():
        immutable_paths.append(task_config_path)
    immutable_paths.extend(data_paths)
    input_hashes = tuple(sorted(
        (
            path.relative_to(task_dir).as_posix(),
            _sha256_file(path),
        )
        for path in immutable_paths
    ))
    snapshot = TaskSnapshot(
        schema_version=1,
        task_id=task_dir.name,
        question=question,
        required_outputs=required_outputs,
        data_files=data_files,
        anchors=anchors,
        required_summary_anchor_ids=tuple(anchor.anchor_id for anchor in summary_anchors),
        input_hashes=input_hashes,
        snapshot_sha256="",
        omitted_data_files=walk_omitted_files + budget_omitted_files,
        data_traversal_truncated=traversal_truncated,
    )
    return replace(snapshot, snapshot_sha256=sha256_text(canonical_json(_snapshot_payload(snapshot))))
