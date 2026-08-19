"""Whole-run integrity seals for completed Harvey experiments."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.harvey_lab.artifacts import (
    file_sha256,
    make_tree_read_only,
    read_json_object,
    validate_regular_tree,
)
from rubric_gen.benchmarks.harvey_lab.config import HarveyExperiment


SEAL_NAME = "run-seal.json"
SEAL_KIND = "rubric-gen-harvey-harness-evolution-seal"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_SEAL_KEYS = {
    "kind",
    "status",
    "experiment_id",
    "experiment_path",
    "experiment_sha256",
    "artifact_count",
    "artifact_bytes",
    "artifact_tree_sha256",
}


def harvey_run_seal_exists(root: Path) -> bool:
    """Return true for any directory entry at the seal path."""
    return os.path.lexists(root / SEAL_NAME)


def _artifact_summary(root: Path) -> tuple[int, int, str]:
    validate_regular_tree(root, "Harvey run")
    digest = hashlib.sha256()
    count = 0
    size = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if relative == SEAL_NAME:
            continue
        mode = os.lstat(path).st_mode
        kind = b"d" if stat.S_ISDIR(mode) else b"f"
        digest.update(kind + b"\0" + relative.encode("utf-8") + b"\0")
        if stat.S_ISREG(mode):
            count += 1
            digest.update(b"x" if mode & 0o111 else b"-")
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
                    size += len(block)
    return count, size, digest.hexdigest()


def _read_seal(experiment: HarveyExperiment) -> dict[str, object]:
    root = experiment.output_dir
    validate_regular_tree(root, "Harvey run")
    path = root / SEAL_NAME
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Harvey run seal is missing or not a regular file: {path}")
    seal = read_json_object(path, "Harvey run seal")
    if (
        set(seal) != _SEAL_KEYS
        or seal.get("kind") != SEAL_KIND
        or seal.get("status") != "sealed"
        or seal.get("experiment_id") != experiment.experiment_id
        or seal.get("experiment_path") != str(experiment.source)
        or seal.get("experiment_sha256") != file_sha256(experiment.source)
        or type(seal.get("artifact_count")) is not int
        or int(seal["artifact_count"]) < 1
        or type(seal.get("artifact_bytes")) is not int
        or int(seal["artifact_bytes"]) < 1
        or type(seal.get("artifact_tree_sha256")) is not str
        or not _HASH.fullmatch(str(seal["artifact_tree_sha256"]))
    ):
        raise ValueError(f"Harvey run seal has invalid fields: {path}")
    observed = _artifact_summary(root)
    expected = (
        seal["artifact_count"],
        seal["artifact_bytes"],
        seal["artifact_tree_sha256"],
    )
    if observed != expected:
        raise ValueError(f"Harvey run seal does not match its artifacts: {path}")
    return seal


def _validate_read_only(root: Path) -> None:
    for path in (root, *root.rglob("*")):
        if os.lstat(path).st_mode & 0o222:
            raise ValueError(f"sealed Harvey run contains a writable path: {path}")


def validate_harvey_run_seal(
    experiment: HarveyExperiment,
) -> dict[str, object]:
    """Validate the strict seal, artifact digest, and read-only tree."""
    seal = _read_seal(experiment)
    _validate_read_only(experiment.output_dir)
    return seal


def seal_harvey_run(experiment: HarveyExperiment) -> dict[str, object]:
    """Seal a complete run or finish a previously interrupted seal operation."""
    root = experiment.output_dir
    path = root / SEAL_NAME
    if harvey_run_seal_exists(root):
        seal = _read_seal(experiment)
    else:
        count, size, digest = _artifact_summary(root)
        if count < 1 or size < 1:
            raise ValueError(f"cannot seal an empty Harvey run: {root}")
        seal = {
            "kind": SEAL_KIND,
            "status": "sealed",
            "experiment_id": experiment.experiment_id,
            "experiment_path": str(experiment.source),
            "experiment_sha256": file_sha256(experiment.source),
            "artifact_count": count,
            "artifact_bytes": size,
            "artifact_tree_sha256": digest,
        }
        write_json_atomic(path, seal)
    make_tree_read_only(root)
    return validate_harvey_run_seal(experiment)
