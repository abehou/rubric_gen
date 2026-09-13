"""Preserve and remove only q6's four known invalid revision directories."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "biomnibench-v21-to45-20260912/results30/da-1-3/study/"
    "biomnibench-da-factorial-r10-81712ed5ed7c/experiments/da-1-3"
)
ARCHIVE_ROOT = Path(__file__).resolve().parent / "failed-revision-evidence" / "after-10421549"
TARGETS = (
    "rep-001/luna/full-static",
    "rep-001/luna/full-red-team-trace",
    "rep-002/luna/full-red-team-trace",
    "rep-003/luna/full-red-team-trace",
)


def _files(root: Path) -> list[Path]:
    paths = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"refusing symlink in failed revision tree: {path}")
        if path.is_file():
            paths.append(path)
    return sorted(paths)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    rows = []
    for relative in TARGETS:
        source = ROOT / relative
        if not source.exists():
            rows.append({"path": relative, "status": "absent"})
            continue
        if not source.is_dir() or source.is_symlink():
            raise RuntimeError(f"refusing non-directory failed revision target: {source}")
        manifest = source / "manifest.json"
        if manifest.is_file():
            rows.append({"path": relative, "status": "manifest_present_not_removed"})
            continue
        archive = ARCHIVE_ROOT / relative
        if archive.exists():
            raise RuntimeError(f"archive already exists: {archive}")
        source_files = _files(source)
        archive.mkdir(parents=True)
        for path in source_files:
            destination = archive / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        source_hashes = {str(p.relative_to(source)): _sha(p) for p in source_files}
        archive_hashes = {str(p.relative_to(archive)): _sha(p) for p in _files(archive)}
        if source_hashes != archive_hashes:
            raise RuntimeError(f"archive verification failed for {source}")
        shutil.rmtree(source)
        rows.append({
            "path": relative,
            "status": "archived_and_removed",
            "file_count": len(source_files),
            "archive": str(archive),
        })
    receipt = {
        "operation": "q6_failed_revision_archive_after_10421549",
        "root": str(ROOT),
        "targets": rows,
        "removed_only_manifestless_targets": True,
    }
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_ROOT / "archive-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
