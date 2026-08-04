"""Bounded, structure-aware retrieval for large forensic transcripts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

INDEX_SCHEMA_VERSION = 5


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _messages(value: Any, pointer: str = "$") -> Iterator[tuple[str, str, str]]:
    if isinstance(value, dict):
        role = value.get("role")
        if isinstance(role, str) and role:
            # The complete structured message is the evidence. In particular,
            # function/tool calls commonly have empty textual content.
            yield pointer, role, _canonical_json(value)
            return
        for key, child in value.items():
            yield from _messages(child, f"{pointer}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _messages(child, f"{pointer}/{index}")


def _jsonl_role(value: Any) -> str:
    if isinstance(value, dict):
        role = value.get("role")
        if isinstance(role, str) and role:
            return role
        kind = value.get("type")
        item = value.get("item")
        if not isinstance(kind, str) and isinstance(item, dict):
            kind = item.get("type")
        if isinstance(kind, str) and kind:
            return f"trajectory:{kind}"
    return "trajectory:event"


def _evidence_records(path: Path) -> Iterator[tuple[str, str, str]]:
    """Yield messages from JSON documents or complete events from JSONL streams."""

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    if path.suffix == ".jsonl":
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            yield (
                f"$line/{line_number}",
                _jsonl_role(event),
                _canonical_json(event),
            )
        return
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return
    yield from _messages(value)


def indexable_event_count(path: Path) -> int:
    """Return the distinct event count that an index would assign to one file."""

    seen: set[tuple[str, str]] = set()
    for _, role, content in _evidence_records(path):
        seen.add((role, hashlib.sha256(content.encode()).hexdigest()))
    return len(seen)


def render_compact_evidence(evidence_dir: Path) -> tuple[str, dict[str, int]]:
    """Render full values once plus every ordered source reference."""
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    references: list[dict[str, Any]] = []
    source_bytes = 0
    for relative in manifest["evidence_files"]:
        path = evidence_dir / relative
        source_bytes += path.stat().st_size
        for pointer, role, value_json in _evidence_records(path):
            digest = hashlib.sha256(value_json.encode()).hexdigest()
            key = (role, digest)
            if key not in seen:
                seen[key] = {
                    "record_type": "event",
                    "event_id": len(seen) + 1,
                    "role": role,
                    "source_references": 0,
                    "value": json.loads(value_json),
                }
            event = seen[key]
            event["source_references"] += 1
            references.append({
                "record_type": "source_reference",
                "reference_id": len(references) + 1,
                "event_id": event["event_id"],
                "location": f"{relative}:{pointer}",
            })
    rendered = "\n".join(
        _canonical_json(record)
        for record in (*seen.values(), *references)
    )
    return rendered, {
        "evidence_schema_version": INDEX_SCHEMA_VERSION,
        "source_bytes": source_bytes,
        "source_references": len(references),
        "distinct_events": len(seen),
        "compact_chars": len(rendered),
    }


def build_evidence_index(evidence_dir: Path, database: Path) -> dict[str, object]:
    """Index complete structured values and their ordered source references."""
    manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
    files = manifest["evidence_files"]
    database.parent.mkdir(parents=True, exist_ok=True)
    temporary = database.with_suffix(database.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    connection.execute("CREATE TABLE metadata (schema_version INTEGER NOT NULL)")
    connection.execute("INSERT INTO metadata VALUES (?)", (INDEX_SCHEMA_VERSION,))
    connection.execute(
        "CREATE TABLE events (event_id INTEGER PRIMARY KEY, "
        "role TEXT NOT NULL, chars INTEGER NOT NULL, "
        "sha256 TEXT NOT NULL, content TEXT NOT NULL, UNIQUE(role, sha256))"
    )
    connection.execute(
        "CREATE TABLE source_references (reference_id INTEGER PRIMARY KEY, "
        "event_id INTEGER NOT NULL, source TEXT NOT NULL, pointer TEXT NOT NULL)"
    )
    roles: Counter[str] = Counter()
    source_bytes = 0
    event_id = 0
    reference_count = 0
    for relative in files:
        path = evidence_dir / relative
        source_bytes += path.stat().st_size
        for pointer, role, value_json in _evidence_records(path):
            digest = hashlib.sha256(value_json.encode()).hexdigest()
            existing = connection.execute(
                "SELECT event_id FROM events WHERE role = ? AND sha256 = ?",
                (role, digest),
            ).fetchone()
            if existing is None:
                event_id += 1
                roles[role] += 1
                connection.execute(
                    "INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                    (event_id, role, len(value_json), digest, value_json),
                )
            else:
                event_id_for_reference = existing[0]
            connection.execute(
                "INSERT INTO source_references (event_id, source, pointer) "
                "VALUES (?, ?, ?)",
                (
                    event_id if existing is None else event_id_for_reference,
                    relative,
                    pointer,
                ),
            )
            reference_count += 1
    connection.execute("CREATE INDEX events_role ON events(role)")
    connection.execute(
        "CREATE INDEX source_references_event ON source_references(event_id)"
    )
    connection.commit()
    connection.close()
    temporary.replace(database)
    return {
        "events": event_id,
        "source_references": reference_count,
        "roles": dict(sorted(roles.items())),
        "source_bytes": source_bytes,
    }


def ensure_evidence_index(evidence_dir: Path, database: Path) -> dict[str, object] | None:
    """Build or replace a missing, partial, or obsolete index."""
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        version = connection.execute("SELECT schema_version FROM metadata").fetchone()
        connection.close()
    except sqlite3.Error:
        version = None
    if version == (INDEX_SCHEMA_VERSION,):
        return None
    return build_evidence_index(evidence_dir, database)


def write_query_tool(
    path: Path,
    database: Path,
    *,
    max_queries: int | None = None,
    counter_path: Path | None = None,
    audit_path: Path | None = None,
) -> None:
    source = f'''#!{__import__("sys").executable}
from pathlib import Path
from rubric_gen.biomnibench.forensics.evidence_index import query_main
raise SystemExit(query_main(
    Path({str(database)!r}),
    max_queries={max_queries!r},
    counter_path={f"Path({str(counter_path)!r})" if counter_path else "None"},
    audit_path={f"Path({str(audit_path)!r})" if audit_path else "None"},
))
'''
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _bounded(text: str, *, start: int, limit: int) -> str:
    end = min(len(text), start + limit)
    suffix = "" if end == len(text) else f"\n...[truncated; continue at --start {end}]"
    return text[start:end] + suffix


def query_main(
    database: Path,
    argv: list[str] | None = None,
    *,
    max_queries: int | None = None,
    counter_path: Path | None = None,
    audit_path: Path | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Bounded forensic evidence retrieval")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory")
    timeline = sub.add_parser("timeline")
    timeline.add_argument("--start", type=int, default=1)
    timeline.add_argument("--limit", type=int, default=80)
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=30)
    search.add_argument("--context", type=int, default=240)
    show = sub.add_parser("show")
    show.add_argument("event_id", type=int)
    show.add_argument("--start", type=int, default=0)
    show.add_argument("--limit", type=int, default=12000)
    references = sub.add_parser("references")
    references.add_argument("event_id", type=int)
    references.add_argument("--start", type=int, default=0)
    references.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if max_queries is not None:
        if max_queries < 1 or counter_path is None:
            raise SystemExit("invalid evidence-query budget configuration")
        try:
            used = int(counter_path.read_text()) if counter_path.exists() else 0
        except (OSError, ValueError) as exc:
            raise SystemExit(f"invalid evidence-query counter: {exc}") from exc
        if used >= max_queries:
            raise SystemExit(
                f"trajectory query budget exhausted ({used}/{max_queries})"
            )
        counter_path.write_text(str(used + 1))
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    retrieved_event_ids: list[int] = []
    if args.command == "inventory":
        rows = connection.execute(
            "SELECT events.role, COUNT(*), "
            "SUM((SELECT COUNT(*) FROM source_references "
            "WHERE source_references.event_id = events.event_id)), "
            "SUM(events.chars), MAX(events.chars) FROM events GROUP BY events.role"
        ).fetchall()
        print("role\tdistinct_events\tsource_references\ttotal_chars\tmax_chars")
        for row in rows:
            print("\t".join(map(str, row)))
        print("total\t" + str(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]))
    elif args.command == "timeline":
        limit = min(max(args.limit, 1), 200)
        rows = connection.execute(
            "SELECT source_references.reference_id, events.event_id, events.role, "
            "events.chars, source_references.source, source_references.pointer, "
            "events.content FROM source_references JOIN events "
            "ON events.event_id = source_references.event_id "
            "WHERE source_references.reference_id >= ? "
            "ORDER BY source_references.reference_id LIMIT ?",
            (max(args.start, 1), limit),
        ).fetchall()
        for reference_id, event_id, role, chars, source, pointer, content in rows:
            retrieved_event_ids.append(event_id)
            preview = " ".join(content[:240].splitlines())
            print(
                f"{reference_id}\tevent:{event_id}\t{role}\t{chars}\t"
                f"{source}:{pointer}\t{preview}"
            )
    elif args.command == "search":
        limit = min(max(args.limit, 1), 100)
        context = min(max(args.context, 40), 1000)
        rows = connection.execute(
            "SELECT events.event_id, events.role, COUNT(source_references.reference_id), "
            "events.chars, MIN(source_references.source), "
            "MIN(source_references.pointer), events.content FROM events "
            "JOIN source_references ON events.event_id = source_references.event_id "
            "WHERE instr(lower(events.content), lower(?)) > 0 "
            "GROUP BY events.event_id ORDER BY events.event_id LIMIT ?",
            (args.query, limit),
        ).fetchall()
        for event_id, role, reference_count, chars, source, pointer, content in rows:
            retrieved_event_ids.append(event_id)
            position = content.lower().find(args.query.lower())
            start = max(0, position - context)
            excerpt = " ".join(content[start:position + len(args.query) + context].splitlines())
            print(
                f"{event_id}\t{role}\treferences:{reference_count}\t{chars}\t"
                f"{source}:{pointer}\t{excerpt}"
            )
    elif args.command == "references":
        limit = min(max(args.limit, 1), 500)
        rows = connection.execute(
            "SELECT reference_id, source, pointer FROM source_references "
            "WHERE event_id = ? ORDER BY reference_id LIMIT ? OFFSET ?",
            (args.event_id, limit, max(args.start, 0)),
        ).fetchall()
        for reference_id, source, pointer in rows:
            print(f"{reference_id}\t{source}:{pointer}")
        if rows:
            retrieved_event_ids.append(args.event_id)
        if len(rows) == limit:
            print(f"...[more may remain; continue at --start {max(args.start, 0) + limit}]")
    else:
        row = connection.execute(
            "SELECT role, chars, content FROM events WHERE event_id = ?",
            (args.event_id,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"unknown event_id: {args.event_id}")
        role, chars, content = row
        reference_summary = connection.execute(
            "SELECT COUNT(*), MIN(reference_id), MAX(reference_id) "
            "FROM source_references WHERE event_id = ?",
            (args.event_id,),
        ).fetchone()
        assert reference_summary is not None
        reference_count, first_reference, last_reference = reference_summary
        first_location = connection.execute(
            "SELECT source, pointer FROM source_references "
            "WHERE reference_id = ?", (first_reference,),
        ).fetchone()
        last_location = connection.execute(
            "SELECT source, pointer FROM source_references "
            "WHERE reference_id = ?", (last_reference,),
        ).fetchone()
        assert first_location is not None and last_location is not None
        retrieved_event_ids.append(args.event_id)
        print(
            f"event_id={args.event_id} role={role} source_references={reference_count} "
            f"chars={chars} first_reference={first_reference} "
            f"first={first_location[0]}:{first_location[1]} "
            f"last_reference={last_reference} "
            f"last={last_location[0]}:{last_location[1]}"
        )
        print(_bounded(content, start=max(args.start, 0), limit=min(max(args.limit, 1), 24000)))
    connection.close()
    if audit_path is not None:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({
                "command": args.command,
                "event_ids": sorted(set(retrieved_event_ids)),
            }, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
    return 0
