"""Build one chronological ledger from revision turn artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rubric_gen.submission_revision.detection_windows import (
    POST_UPDATE_BASELINE_INDEX,
    POST_UPDATE_FIRST_AFFECTED_INDEX,
    RevisionDetectionWindow,
)


@dataclass(frozen=True, slots=True)
class EvidenceLedgerEntry:
    source: str
    value: object


@dataclass(frozen=True, slots=True)
class RevisionEvidenceLedger:
    submission_ids: tuple[str, ...]
    latest_submission: Path
    entries: tuple[EvidenceLedgerEntry, ...]
    source_bytes: int
    source_records: int
    solver_feedback_records: int
    superseded_started_events: int


@dataclass(frozen=True, slots=True)
class RenderedEvidenceLedger:
    text: str
    distinct_events: int
    exact_duplicate_records: int
    exact_duplicate_chars_saved: int


@dataclass(frozen=True, slots=True)
class EvidenceBlinder:
    task_id: str
    condition_id: str | None

    def __call__(self, value: object) -> object:
        if isinstance(value, str):
            redacted = re.sub(
                rf"(?i)(?<![A-Za-z0-9]){re.escape(self.task_id)}(?![A-Za-z0-9])",
                "[TASK_ID]",
                value,
            )
            if self.condition_id is not None:
                redacted = re.sub(
                    rf"(?i)(?<![A-Za-z0-9])"
                    rf"{re.escape(self.condition_id)}(?![A-Za-z0-9])",
                    "[CONDITION]",
                    redacted,
                )
            return redacted
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self(item) for key, item in value.items()}
        return value


def load_revision_evidence_ledger(
    revision_dir: Path,
    manifest: dict[str, object],
    window: RevisionDetectionWindow,
    blind: Callable[[object], object],
) -> RevisionEvidenceLedger:
    """Read each trajectory segment once and preserve its source order."""

    resolved_window = RevisionDetectionWindow(window)
    state = _load_state(revision_dir)
    submission_ids = _validated_submission_ids(revision_dir, manifest, state)
    submissions_root = revision_dir / "submissions"
    latest_submission = submissions_root / submission_ids[-1]
    latest_path = latest_submission / "trajectory.stream.jsonl"
    if latest_path.is_symlink() or not latest_path.is_file():
        raise ValueError(f"revision has no cumulative trajectory: {latest_submission}")

    segments = _trajectory_segments(revision_dir, submissions_root, submission_ids)
    segment_bytes = tuple(path.read_bytes() for path in segments)
    segment_lines = tuple(_decode_lines(raw) for raw in segment_bytes)
    latest_bytes = (
        segment_bytes[0]
        if latest_path == segments[0]
        else latest_path.read_bytes()
    )
    if _canonical_cumulative_bytes(segment_bytes) != latest_bytes:
        raise ValueError(
            f"latest trajectory differs from its turn ledger: {revision_dir}"
        )
    no_change = _no_change_turn(revision_dir, state, len(submission_ids))
    no_change_bytes = no_change[0].read_bytes() if no_change is not None else None
    no_change_lines = (
        _decode_lines(no_change_bytes) if no_change_bytes is not None else ()
    )
    completed_item_ids = _completed_item_ids(
        line for lines in (*segment_lines, no_change_lines) for line in lines
    )

    entries: list[EvidenceLedgerEntry] = []
    normalization_stats = {"superseded_started_events": 0}
    source_records = 0
    source_bytes = 0
    feedback_records = 0
    global_line = 0
    feedback_root = revision_dir / "feedback"
    for submission_index, (raw, lines) in enumerate(
        zip(segment_bytes, segment_lines, strict=True)
    ):
        include_trajectory = (
            resolved_window is RevisionDetectionWindow.FULL_TRAJECTORY
            or (
                resolved_window is RevisionDetectionWindow.POST_UPDATE
                and submission_index >= POST_UPDATE_FIRST_AFFECTED_INDEX
            )
            or (
                resolved_window is RevisionDetectionWindow.FINAL_REVISION
                and submission_index == len(submission_ids) - 1
            )
        )
        if include_trajectory:
            source_bytes += _normalized_size(raw)
        for line in lines:
            global_line += 1
            if not include_trajectory:
                continue
            source_records += 1
            normalized = _normalize_event(
                blind(_parse_line(line)),
                completed_item_ids=completed_item_ids,
                stats=normalization_stats,
            )
            if normalized is not None:
                entries.append(EvidenceLedgerEntry(
                    source=f"trajectory:{global_line}",
                    value=normalized,
                ))
        if submission_index == len(submission_ids) - 1 and no_change is None:
            continue
        include_feedback = (
            resolved_window is RevisionDetectionWindow.FULL_TRAJECTORY
            or (
                resolved_window is RevisionDetectionWindow.POST_UPDATE
                and submission_index >= POST_UPDATE_BASELINE_INDEX
            )
            or (
                resolved_window is RevisionDetectionWindow.FINAL_REVISION
                and submission_index == len(submission_ids) - 2
            )
        )
        if not include_feedback:
            continue
        submission_id = submission_ids[submission_index]
        entries.append(EvidenceLedgerEntry(
            source=f"solver_feedback:{submission_id}",
            value=blind(_load_feedback(feedback_root, submission_id, revision_dir)),
        ))
        feedback_records += 1

    if no_change is not None:
        path, stop_record = no_change
        include_stop = (
            resolved_window is RevisionDetectionWindow.FULL_TRAJECTORY
            or (
                resolved_window is RevisionDetectionWindow.POST_UPDATE
                and len(submission_ids) >= POST_UPDATE_FIRST_AFFECTED_INDEX
            )
        )
        if include_stop:
            assert no_change_bytes is not None
            source_bytes += _normalized_size(no_change_bytes)
            turn_name = path.parent.name
            for line_number, line in enumerate(no_change_lines, start=1):
                source_records += 1
                normalized = _normalize_event(
                    blind(_parse_line(line)),
                    completed_item_ids=completed_item_ids,
                    stats=normalization_stats,
                )
                if normalized is not None:
                    entries.append(EvidenceLedgerEntry(
                        source=f"turn:{turn_name}:trajectory:{line_number}",
                        value=normalized,
                    ))
            entries.append(EvidenceLedgerEntry(
                source=f"automatic_stop:{turn_name}",
                value=stop_record,
            ))

    return RevisionEvidenceLedger(
        submission_ids=submission_ids,
        latest_submission=latest_submission,
        entries=tuple(entries),
        source_bytes=source_bytes,
        source_records=source_records,
        solver_feedback_records=feedback_records,
        superseded_started_events=normalization_stats[
            "superseded_started_events"
        ],
    )


def load_final_revision_evidence_ledger(
    revision_dir: Path,
    manifest: dict[str, object],
    blind: Callable[[object], object],
) -> RevisionEvidenceLedger:
    """Read only the last artifact-producing revision and its input feedback."""

    state = _load_state(revision_dir)
    submission_ids = _validated_submission_ids(revision_dir, manifest, state)
    if len(submission_ids) < 2:
        raise ValueError(
            f"revision does not reach the final-revision window: {revision_dir}"
        )
    submissions_root = revision_dir / "submissions"
    latest_submission = submissions_root / submission_ids[-1]
    path = (
        revision_dir
        / "turns"
        / f"turn-{len(submission_ids) - 1:03d}"
        / "trajectory.stream.jsonl"
    )
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"revision final trajectory segment is missing: {path}")
    raw = path.read_bytes()
    lines = _decode_lines(raw)
    completed_item_ids = _completed_item_ids(lines)
    normalization_stats = {"superseded_started_events": 0}
    entries: list[EvidenceLedgerEntry] = []
    for line_number, line in enumerate(lines, start=1):
        normalized = _normalize_event(
            blind(_parse_line(line)),
            completed_item_ids=completed_item_ids,
            stats=normalization_stats,
        )
        if normalized is not None:
            entries.append(EvidenceLedgerEntry(
                source=f"trajectory:{line_number}",
                value=normalized,
            ))
    prior_submission_id = submission_ids[-2]
    entries.insert(0, EvidenceLedgerEntry(
        source=f"solver_feedback:{prior_submission_id}",
        value=blind(_load_feedback(
            revision_dir / "feedback",
            prior_submission_id,
            revision_dir,
        )),
    ))
    return RevisionEvidenceLedger(
        submission_ids=submission_ids,
        latest_submission=latest_submission,
        entries=tuple(entries),
        source_bytes=_normalized_size(raw),
        source_records=len(lines),
        solver_feedback_records=1,
        superseded_started_events=normalization_stats[
            "superseded_started_events"
        ],
    )


def render_evidence_ledger(
    entries: tuple[EvidenceLedgerEntry, ...],
) -> RenderedEvidenceLedger:
    """Render a chronological ledger with exact-value references."""

    records: list[str] = []
    first_event_by_value: dict[str, int] = {}
    duplicate_records = 0
    duplicate_chars_saved = 0
    for entry in entries:
        event_id = len(records) + 1
        canonical = json.dumps(
            entry.value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        record: dict[str, object] = {
            "event_id": event_id,
            "source": entry.source,
            "value": entry.value,
        }
        first_event = first_event_by_value.get(canonical)
        if first_event is None:
            first_event_by_value[canonical] = event_id
        else:
            reference = {
                "event_id": event_id,
                "source": entry.source,
                "value_reference": {"same_as_event_id": first_event},
            }
            full_text = _render_record(record)
            reference_text = _render_record(reference)
            saved = len(full_text) - len(reference_text)
            if saved > 0:
                record = reference
                duplicate_records += 1
                duplicate_chars_saved += saved
        records.append(_render_record(record))
    return RenderedEvidenceLedger(
        text="\n".join(records),
        distinct_events=len(records),
        exact_duplicate_records=duplicate_records,
        exact_duplicate_chars_saved=duplicate_chars_saved,
    )


def _load_state(revision_dir: Path) -> dict[str, object]:
    try:
        value = json.loads((revision_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"revision has invalid state: {revision_dir}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"revision has invalid state: {revision_dir}")
    return value


def _validated_submission_ids(
    revision_dir: Path,
    manifest: dict[str, object],
    state: dict[str, object],
) -> tuple[str, ...]:
    raw_ids = state.get("submission_ids")
    scores = state.get("scores")
    if (
        state.get("phase") != "completed"
        or not isinstance(raw_ids, list)
        or not raw_ids
        or any(type(value) is not str for value in raw_ids)
        or raw_ids != [f"s{index:03d}" for index in range(len(raw_ids))]
        or not isinstance(scores, list)
        or len(scores) != len(raw_ids)
        or state.get("next_turn_index") != len(raw_ids)
        or manifest.get("submission_count") != len(raw_ids)
    ):
        raise ValueError(f"revision is not completely scored: {revision_dir}")
    submission_ids = tuple(raw_ids)
    submissions_root = revision_dir / "submissions"
    if submissions_root.is_symlink() or not submissions_root.is_dir():
        raise ValueError(f"revision has no submission set: {revision_dir}")
    observed_ids = sorted(
        path.name
        for path in submissions_root.iterdir()
        if path.is_dir() and not path.is_symlink()
    )
    if observed_ids != list(submission_ids):
        raise ValueError(f"revision submission set is inconsistent: {revision_dir}")
    return submission_ids


def _trajectory_segments(
    revision_dir: Path,
    submissions_root: Path,
    submission_ids: tuple[str, ...],
) -> tuple[Path, ...]:
    paths = [submissions_root / submission_ids[0] / "trajectory.stream.jsonl"]
    paths.extend(
        revision_dir / "turns" / f"turn-{index:03d}" / "trajectory.stream.jsonl"
        for index in range(1, len(submission_ids))
    )
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"revision trajectory segment is missing: {path}")
    return tuple(paths)


def _canonical_cumulative_bytes(segments: tuple[bytes, ...]) -> bytes:
    parts: list[bytes] = []
    for raw in segments:
        parts.append(raw)
        if raw and not raw.endswith(b"\n"):
            parts.append(b"\n")
    return b"".join(parts)


def _no_change_turn(
    revision_dir: Path,
    state: dict[str, object],
    submission_count: int,
) -> tuple[Path, dict[str, object]] | None:
    turn_dir = revision_dir / "turns" / f"turn-{submission_count:03d}"
    if turn_dir.is_symlink():
        raise ValueError(f"revision no-change turn is symlinked: {turn_dir}")
    if not turn_dir.exists():
        return None
    if not turn_dir.is_dir() or state.get("stop_reason") != "no_change":
        raise ValueError(f"revision has an invalid no-change turn: {turn_dir}")
    path = turn_dir / "trajectory.stream.jsonl"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"revision no-change turn has no trajectory: {turn_dir}")
    return path, {"reason": "no_change", "submission_changed": False}


def _completed_item_ids(lines: Iterable[str]) -> set[str]:
    completed: set[str] = set()
    for line in lines:
        value = _parse_line(line)
        if isinstance(value, dict) and value.get("type") == "item.completed":
            item = value.get("item")
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                completed.add(item["id"])
    return completed


def _normalize_event(
    value: object,
    *,
    completed_item_ids: set[str],
    stats: dict[str, int],
) -> object | None:
    if not isinstance(value, dict):
        return value
    event_type = value.get("type")
    item = value.get("item")
    if (
        event_type == "item.started"
        and isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"] in completed_item_ids
    ):
        stats["superseded_started_events"] += 1
        return None
    normalized = dict(value)
    if isinstance(item, dict):
        normalized_item = dict(item)
        normalized_item.pop("id", None)
        if event_type == "item.completed":
            normalized_item.pop("status", None)
        normalized["item"] = normalized_item
    if event_type == "thread.started":
        normalized.pop("thread_id", None)
    if event_type == "turn.completed":
        normalized.pop("usage", None)
    return normalized


def _load_feedback(
    feedback_root: Path,
    submission_id: str,
    revision_dir: Path,
) -> object:
    path = feedback_root / f"{submission_id}.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            "submission revision lacks solver-visible feedback for "
            f"{submission_id}: {revision_dir}"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"submission revision has invalid feedback for {submission_id}: "
            f"{revision_dir}"
        ) from exc


def _decode_lines(raw: bytes) -> tuple[str, ...]:
    return tuple(raw.decode("utf-8", errors="replace").splitlines())


def _normalized_size(raw: bytes) -> int:
    return len(raw) + int(bool(raw) and not raw.endswith(b"\n"))


def _parse_line(line: str) -> object:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"raw": line}


def _render_record(record: dict[str, object]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))
