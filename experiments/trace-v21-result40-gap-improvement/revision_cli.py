"""Run pilot revision recovery with process-local sealed-tree hash reuse."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import threading

from rubric_gen.cli import main as _cli_main
from rubric_gen.submission_revision import red_team


_ORIGINAL_TREE_SHA256 = red_team.tree_sha256
_CACHE: dict[str, tuple[tuple[tuple[object, ...], ...], str]] = {}
_CACHE_LOCK = threading.Lock()


def _tree_stamp(root: Path) -> tuple[tuple[object, ...], ...]:
    """Capture metadata that changes on ordinary tree or content mutation."""

    root = root.absolute()
    paths = (root, *sorted(root.rglob("*"), key=lambda path: str(path)))
    stamp = []
    for path in paths:
        value = os.lstat(path)
        stamp.append(
            (
                str(path.relative_to(root.parent)),
                value.st_mode,
                value.st_dev,
                value.st_ino,
                value.st_size,
                value.st_mtime_ns,
                value.st_ctime_ns,
            )
        )
    return tuple(stamp)


def cached_tree_sha256(root: Path) -> str:
    """Reuse a hash only while the sealed tree's full metadata is unchanged."""

    root = Path(root).absolute()
    if not (
        root.name == "workspace"
        and root.parent.name.startswith("checkpoint-")
        and root.parent.parent.name == "red-team"
    ):
        return _ORIGINAL_TREE_SHA256(root)
    key = str(root)
    before = _tree_stamp(root)
    if any(int(item[1]) & 0o222 for item in before):
        return _ORIGINAL_TREE_SHA256(root)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None and cached[0] == before:
        return cached[1]
    digest = _ORIGINAL_TREE_SHA256(root)
    after = _tree_stamp(root)
    if after != before:
        raise RuntimeError(f"red-team tree changed while hashing: {root}")
    with _CACHE_LOCK:
        _CACHE[key] = (after, digest)
    return digest


def run(argv: list[str]) -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("revision recovery must run through Slurm")
    if not argv or argv[0] != "--experiment" or "--resume" not in argv:
        raise ValueError("sealed-tree reuse is only valid for revision resume")
    original = red_team.tree_sha256
    red_team.tree_sha256 = cached_tree_sha256
    try:
        return _cli_main(["revise", *argv])
    finally:
        red_team.tree_sha256 = original


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
