"""Finish the exact q7 failed-seed archive after its first removal attempt.

The first archive copied and verified the manifestless target but could not
remove one permission-protected failed workspace entry.  This script verifies
that existing archive again, makes only that exact failed target owner-writable,
and removes it.  It never searches for or deletes another path.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

TARGET = Path("/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results45-added15/da-17-1/inputs/seeds/tasks/da-17-1/rep-003")
# The failed-seed evidence is owned by the q7 input-preparation worktree.  Keep
# this explicit so a q6 consumer cannot accidentally resolve a sibling path in
# its own queue8 directory.
ARCHIVE = Path(
    "/home/aydanh/repos/rubric_gen/runs/babel-code/"
    "trace-results45-inputs-20260912/experiments/biomnibench-v21-to45/"
    "queue7/failed-seed-evidence/da-17-1-rep-003-attempt4"
)
RECEIPT = Path(__file__).resolve().parent / "q7-seed-archive-completion.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def writable(path: Path) -> None:
    """Grant owner-only write/search bits to the exact failed target tree."""
    paths = sorted(TARGET.rglob("*"), key=lambda p: len(p.parts), reverse=True)
    for path in paths + [TARGET]:
        try:
            mode = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0)
            os.chmod(path, mode)
        except PermissionError as exc:
            raise RuntimeError(f"cannot make exact failed target writable: {path}") from exc


def main() -> int:
    if RECEIPT.exists():
        raise RuntimeError(f"completion receipt already exists: {RECEIPT}")
    if not TARGET.is_dir() or TARGET.is_symlink():
        raise RuntimeError(f"failed seed target is not an ordinary directory: {TARGET}")
    if (TARGET / "manifest.json").exists():
        raise RuntimeError("refusing a target that now contains manifest.json")
    if not ARCHIVE.is_dir():
        raise RuntimeError(f"attempt4 archive is missing: {ARCHIVE}")
    listing = ARCHIVE / "files.tsv"
    if not listing.is_file():
        raise RuntimeError(f"attempt4 archive has no files.tsv: {listing}")
    checked = 0
    for line in listing.read_text(encoding="utf-8").splitlines()[1:]:
        if not line:
            continue
        relative, _size, expected = line.split("\t", 2)
        source = TARGET / relative
        archived = ARCHIVE / relative
        if not source.is_file() or not archived.is_file() or digest(source) != expected or digest(archived) != expected:
            raise RuntimeError(f"archive verification failed for {relative}")
        checked += 1
    writable(TARGET)
    shutil.rmtree(TARGET)
    if TARGET.exists():
        raise RuntimeError(f"failed seed target remains after removal: {TARGET}")
    receipt = {
        "source": str(TARGET), "archive": str(ARCHIVE), "attempt": 4,
        "completed_after_permission_repair": True, "verified_archived_files": checked,
        "removed_exact_target": True, "preserved_failed_output": True,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
