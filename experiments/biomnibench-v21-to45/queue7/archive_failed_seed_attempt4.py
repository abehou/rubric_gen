"""Archive the second failed da-17-1 seed target before native retry.

This is an exact, task-local cleanup: it refuses a manifest-bearing target,
copies every remaining failure file to the small home receipt, verifies the
copy, then removes only the failed replicate directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


TARGET = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "biomnibench-v21-to45-20260912/results45-added15/da-17-1/inputs/"
    "seeds/tasks/da-17-1/rep-003"
)
ARCHIVE = Path(__file__).resolve().parent / "failed-seed-evidence" / "da-17-1-rep-003-attempt4"


def _files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    )


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    if not TARGET.is_dir() or TARGET.is_symlink():
        raise RuntimeError(f"failed seed target is not an ordinary directory: {TARGET}")
    if (TARGET / "manifest.json").exists():
        raise RuntimeError("refusing to archive a target that contains manifest.json")
    if ARCHIVE.exists():
        raise RuntimeError(f"archive already exists: {ARCHIVE}")

    source_files = _files(TARGET)
    ARCHIVE.mkdir(parents=True)
    for source in source_files:
        relative = source.relative_to(TARGET)
        destination = ARCHIVE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    archived_files = _files(ARCHIVE)
    source_hashes = {
        str(path.relative_to(TARGET)): _digest(path) for path in source_files
    }
    archive_hashes = {
        str(path.relative_to(ARCHIVE)): _digest(path) for path in archived_files
    }
    if source_hashes != archive_hashes:
        raise RuntimeError("archived failed-seed files do not match the target")
    (ARCHIVE / "files.tsv").write_text(
        "path\tbytes\tsha256\n"
        + "\n".join(
            f"{name}\t{(ARCHIVE / name).stat().st_size}\t{digest}"
            for name, digest in sorted(archive_hashes.items())
        )
        + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(TARGET)
    if TARGET.exists():
        raise RuntimeError(f"failed seed target remains after cleanup: {TARGET}")
    receipt = {
        "source": str(TARGET),
        "archive": str(ARCHIVE),
        "attempt": 4,
        "removed_exact_target": True,
        "preserved_files": len(source_files),
        "preserved_failed_output": True,
        "manifest_present_before_cleanup": False,
    }
    (ARCHIVE / "archive-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
