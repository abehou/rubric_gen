"""Crash-safe serialization helpers for durable run metadata."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_json_atomic(path: Path, value: object) -> None:
    """Atomically replace a JSON file and sync both contents and directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()
