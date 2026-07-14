"""Deterministic, race-aware snapshots of immutable BiomniBench task inputs."""

from __future__ import annotations

import codecs
import csv
import hashlib
import heapq
import io
import os
import re
import stat
from dataclasses import replace
from itertools import islice
from pathlib import Path

from rubric_gen.biomnibench.task_rubrics import (
    DataFileSnapshot,
    SchemaSnapshotLimits,
    TaskAnchor,
    TaskSnapshot,
    _ImmutableFileSnapshot,
    canonical_json,
    sha256_text,
)


def _snapshot_payload(snapshot: TaskSnapshot) -> dict[str, object]:
    payload = snapshot.to_dict()
    payload.pop("snapshot_sha256")
    return payload


def _stable_file_signature(
    file_stat: os.stat_result,
) -> tuple[int, int, int, int, int | None]:
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_size,
        file_stat.st_mtime_ns,
        getattr(file_stat, "st_ctime_ns", None),
    )


def _snapshot_immutable_file(
    path: Path,
    *,
    capture_bytes: int | None,
    context: str,
) -> _ImmutableFileSnapshot:
    """Hash and capture one stable regular file through a single descriptor."""

    if capture_bytes is not None and capture_bytes < 0:
        raise ValueError("capture_bytes must be non-negative or None")
    if _first_symlink_component(path) is not None:
        raise ValueError(f"{context} must be a regular, non-symlink file")
    try:
        before_path = path.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ValueError(f"{context} must be a regular, non-symlink file") from exc
    if not stat.S_ISREG(before_path.st_mode):
        raise ValueError(f"{context} must be a regular, non-symlink file")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"{context} must be a regular, non-symlink file") from exc

    digest = hashlib.sha256()
    captured = bytearray()
    bytes_seen = 0
    try:
        before_fd = os.fstat(fd)
        if not stat.S_ISREG(before_fd.st_mode) or _stable_file_signature(
            before_fd
        ) != _stable_file_signature(before_path):
            raise ValueError(f"{context} changed while being snapshotted")

        while True:
            chunk = os.read(fd, 65_536)
            if not chunk:
                break
            bytes_seen += len(chunk)
            digest.update(chunk)
            if capture_bytes is None:
                captured.extend(chunk)
            elif len(captured) < capture_bytes:
                remaining = capture_bytes - len(captured)
                captured.extend(chunk[:remaining])

        after_fd = os.fstat(fd)
        try:
            after_path = path.lstat()
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise ValueError(f"{context} changed while being snapshotted") from exc
        if (
            _first_symlink_component(path) is not None
            or not stat.S_ISREG(after_path.st_mode)
            or _stable_file_signature(before_fd) != _stable_file_signature(after_fd)
            or _stable_file_signature(after_fd) != _stable_file_signature(after_path)
            or bytes_seen != after_fd.st_size
        ):
            raise ValueError(f"{context} changed while being snapshotted")
    finally:
        os.close(fd)

    return _ImmutableFileSnapshot(
        size_bytes=after_fd.st_size,
        sha256=digest.hexdigest(),
        captured_bytes=bytes(captured),
    )


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _first_symlink_component(path: Path) -> Path | None:
    absolute = _absolute_without_resolving(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError):
            return None
        if stat.S_ISLNK(mode):
            return current
    return None


def _validated_task_root(task_dir: Path) -> Path:
    task_root = _absolute_without_resolving(task_dir)
    symlink = _first_symlink_component(task_root)
    if symlink is not None:
        raise ValueError(f"task directory has a symlinked path component: {symlink}")
    try:
        mode = task_root.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ValueError(f"task directory does not exist: {task_root}") from exc
    if not stat.S_ISDIR(mode):
        raise ValueError(f"task directory must be a directory: {task_root}")
    return task_root


def _validated_task_input(
    task_root: Path,
    relative_path: str,
    *,
    required: bool,
) -> Path | None:
    path = task_root / relative_path
    symlink = _first_symlink_component(path)
    if symlink is not None:
        if symlink == path:
            raise ValueError(f"{relative_path} must be a regular, non-symlink file")
        raise ValueError(f"{relative_path} has a symlinked path component: {symlink}")
    try:
        mode = path.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError) as exc:
        if not required:
            return None
        raise ValueError(
            f"{relative_path} must be a regular, non-symlink file"
        ) from exc
    if not stat.S_ISREG(mode):
        raise ValueError(f"{relative_path} must be a regular, non-symlink file")
    try:
        path.resolve(strict=True).relative_to(task_root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            f"{relative_path} must be contained under the task directory"
        ) from exc
    return path


def _validated_data_root(task_root: Path) -> Path:
    data_root = task_root / "environment" / "data"
    symlink = _first_symlink_component(data_root)
    if symlink is not None:
        raise ValueError(f"environment/data has a symlinked path component: {symlink}")
    return data_root


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
    relative_path: str,
    limits: SchemaSnapshotLimits,
    *,
    file_snapshot: _ImmutableFileSnapshot,
) -> DataFileSnapshot:
    probe = file_snapshot.captured_bytes
    probe_truncated = len(probe) > limits.max_probe_bytes
    probe = probe[: limits.max_probe_bytes]
    common = {
        "path": relative_path,
        "size_bytes": file_snapshot.size_bytes,
        "sha256": file_snapshot.sha256,
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


def _walk_data_file_inventory(
    data_root: Path,
    limits: SchemaSnapshotLimits,
) -> tuple[tuple[Path, ...], bool]:
    if not data_root.is_dir():
        return (), False
    pending = [("", data_root)]
    files: list[Path] = []
    entries_enumerated = 0
    traversal_truncated = False
    while pending:
        _, path = heapq.heappop(pending)
        if path.is_symlink():
            relative = (
                "." if path == data_root else path.relative_to(data_root).as_posix()
            )
            raise ValueError(f"environment/data contains a symlink entry: {relative}")
        if path.is_dir():
            remaining = limits.max_entries_visited - entries_enumerated
            if remaining == 0:
                if next(path.iterdir(), None) is not None:
                    traversal_truncated = True
                continue
            children = list(islice(path.iterdir(), remaining + 1))
            if len(children) > remaining:
                entries_enumerated = limits.max_entries_visited
                traversal_truncated = True
                continue
            for child in children:
                if child.is_symlink():
                    relative = child.relative_to(data_root).as_posix()
                    raise ValueError(
                        f"environment/data contains a symlink entry: {relative}"
                    )
            entries_enumerated += len(children)
            for child in sorted(
                children,
                key=lambda item: item.relative_to(data_root).as_posix(),
            ):
                relative = child.relative_to(data_root).as_posix()
                heapq.heappush(pending, (relative, child))
        elif path.is_file():
            files.append(path)
    return tuple(files), traversal_truncated


def _walk_data_files(
    data_root: Path,
    limits: SchemaSnapshotLimits,
) -> tuple[tuple[Path, ...], int, bool]:
    """Return the bounded schema-preview paths and their omission metadata."""

    inventory, traversal_truncated = _walk_data_file_inventory(data_root, limits)
    preview = inventory[: limits.max_files]
    return (
        preview,
        len(inventory) - len(preview),
        traversal_truncated,
    )


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
    next_heading = re.search(r"^##\s+", text[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_heading.start() if next_heading else len(text)
    return text[match.end() : end].strip()


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
    matches = list(
        re.finditer(r"^Criterion\s+(\d+)\s*:\s*(.+?)\s*$", rubric, re.MULTILINE)
    )
    anchors: list[TaskAnchor] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(rubric)
        block = rubric[match.start() : end].strip()
        anchors.append(
            TaskAnchor(
                anchor_id=f"summary:C{int(match.group(1))}",
                kind="summary-criterion",
                text=block,
                source="tests/rubric.txt",
            )
        )
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
        anchors.append(
            TaskAnchor(
                f"data:{data_file.path}",
                "data-file",
                data_file.path,
                source,
            )
        )
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

    task_root = _validated_task_root(task_dir)
    instruction_path = _validated_task_input(
        task_root,
        "instruction.md",
        required=True,
    )
    rubric_path = _validated_task_input(
        task_root,
        "tests/rubric.txt",
        required=True,
    )
    task_config_path = _validated_task_input(
        task_root,
        "task.toml",
        required=False,
    )
    assert instruction_path is not None
    assert rubric_path is not None
    instruction_file = _snapshot_immutable_file(
        instruction_path,
        capture_bytes=None,
        context="instruction.md",
    )
    rubric_file = _snapshot_immutable_file(
        rubric_path,
        capture_bytes=None,
        context="tests/rubric.txt",
    )
    task_config_file = (
        _snapshot_immutable_file(
            task_config_path,
            capture_bytes=None,
            context="task.toml",
        )
        if task_config_path is not None
        else None
    )
    instruction = instruction_file.captured_bytes.decode("utf-8")
    rubric = rubric_file.captured_bytes.decode("utf-8")

    data_root = _validated_data_root(task_root)
    data_paths, traversal_truncated = _walk_data_file_inventory(data_root, limits)
    if traversal_truncated:
        raise ValueError(
            "environment/data traversal exceeded max_entries_visited "
            f"limit {limits.max_entries_visited}; refusing a partial snapshot"
        )
    data_inventory: list[tuple[str, _ImmutableFileSnapshot]] = []
    for index, path in enumerate(data_paths):
        relative_path = path.relative_to(data_root).as_posix()
        try:
            path.resolve(strict=True).relative_to(data_root.resolve(strict=True))
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError(
                f"environment/data source must be contained under data root: {path}"
            ) from exc
        capture_bytes = limits.max_probe_bytes + 1 if index < limits.max_files else 0
        data_inventory.append(
            (
                relative_path,
                _snapshot_immutable_file(
                    path,
                    capture_bytes=capture_bytes,
                    context=f"environment/data/{relative_path}",
                ),
            )
        )

    preview_inventory = data_inventory[: limits.max_files]
    walk_omitted_files = len(data_inventory) - len(preview_inventory)
    probed_data_files = tuple(
        _table_snapshot(
            relative_path,
            limits,
            file_snapshot=file_snapshot,
        )
        for relative_path, file_snapshot in preview_inventory
    )
    data_files, budget_omitted_files = _fit_schema_budget(
        probed_data_files,
        limits.max_output_chars,
    )
    question = " ".join(_extract_markdown_section(instruction, "Question").split())
    required_outputs = _extract_required_outputs(instruction)
    summary_anchors = _summary_anchors(rubric)
    anchors = _task_anchors(question, required_outputs, summary_anchors, data_files)
    input_hashes = tuple(
        sorted(
            [
                ("instruction.md", instruction_file.sha256),
                ("tests/rubric.txt", rubric_file.sha256),
            ]
            + (
                [("task.toml", task_config_file.sha256)]
                if task_config_file is not None
                else []
            )
            + [
                (f"environment/data/{relative_path}", file_snapshot.sha256)
                for relative_path, file_snapshot in data_inventory
            ]
        )
    )
    snapshot = TaskSnapshot(
        schema_version=1,
        task_id=task_root.name,
        question=question,
        required_outputs=required_outputs,
        data_files=data_files,
        anchors=anchors,
        required_summary_anchor_ids=tuple(
            anchor.anchor_id for anchor in summary_anchors
        ),
        input_hashes=input_hashes,
        snapshot_sha256="",
        omitted_data_files=walk_omitted_files + budget_omitted_files,
        data_traversal_truncated=traversal_truncated,
    )
    return replace(
        snapshot,
        snapshot_sha256=sha256_text(canonical_json(_snapshot_payload(snapshot))),
    )
