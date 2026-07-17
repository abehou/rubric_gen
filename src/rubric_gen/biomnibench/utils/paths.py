"""Project path resolution."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]


def resolve_project_path(path: str | Path) -> Path:
    """Resolve a CLI path relative to the repository root."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (PROJECT_ROOT / candidate).resolve()
