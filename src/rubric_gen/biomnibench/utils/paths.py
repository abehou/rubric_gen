"""Project path resolution."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DIRECTORY_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")


def directory_component(value: object) -> str:
    """Return a bounded, portable directory-name component."""
    text = str(value) if value is not None else "default"
    compact = _DIRECTORY_COMPONENT_RE.sub("-", text).strip(".-") or "default"
    if len(compact) <= 48:
        return compact
    digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:8]
    return f"{compact[:39]}-{digest}"


def resolve_project_path(path: str | Path) -> Path:
    """Resolve a CLI path relative to the repository root."""
    if _CONTROL_CHARACTER_RE.search(str(path)):
        raise ValueError("paths must not contain control characters")
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (PROJECT_ROOT / candidate).resolve()
