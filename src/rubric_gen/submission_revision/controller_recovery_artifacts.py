"""Validate and clean revision recovery artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from pathlib import Path


def fixed_original_attempt_id(
    assignment_id: str,
    submission_id: str,
    rubric_sha256: str,
) -> str:
    """Return the deterministic attempt ID for a fixed-original cross-score."""
    return hashlib.sha256(
        (
            "fixed-original\0"
            + assignment_id
            + "\0"
            + submission_id
            + "\0"
            + rubric_sha256
        ).encode("utf-8")
    ).hexdigest()[:32]


def numbered_bank_directories(
    root: Path,
    *,
    required: bool,
    context: str,
) -> list[int]:
    """Return strict canonical bank directory numbers."""

    if not os.path.lexists(root):
        if required:
            raise RuntimeError(f"{context} root is missing")
        return []
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"{context} root is invalid")
    rounds: list[int] = []
    for path in root.iterdir():
        name = path.name
        if (
            path.is_symlink()
            or not path.is_dir()
            or len(name) != 9
            or not name.startswith("bank-")
            or not name[5:].isdigit()
        ):
            raise RuntimeError(f"{context} root contains an invalid entry")
        rounds.append(int(name[5:]))
    if len(set(rounds)) != len(rounds):
        raise RuntimeError(f"{context} root contains duplicate rounds")
    return sorted(rounds)


def rubric_generation_entries(
    root: Path,
) -> list[int]:
    """Return completed rubric-generation rounds."""

    if not os.path.lexists(root):
        return []
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("rubric generation root is invalid")
    rounds: list[int] = []
    for path in root.iterdir():
        name = path.name
        if (
            not path.is_symlink()
            and path.is_dir()
            and len(name) == 9
            and name.startswith("bank-")
            and name[5:].isdigit()
        ):
            rounds.append(int(name[5:]))
            continue
        raise RuntimeError("rubric generation root contains an invalid entry")
    if len(set(rounds)) != len(rounds):
        raise RuntimeError("rubric generation root contains duplicate rounds")
    return sorted(rounds)


_GENERATION_STAGING_DIRECTORY = re.compile(
    r"^\.bank-([0-9]{4})\.[a-z0-9_]{8}$"
)


def remove_owned_rubric_generation_residue(
    root: Path,
    *,
    max_generation_round: int,
) -> None:
    """Remove only interrupted atomic writes and generation staging trees."""

    if not os.path.lexists(root):
        return
    root_stat = os.lstat(root)
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise RuntimeError("rubric generation root is invalid")
    changed = False
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        stage_match = _GENERATION_STAGING_DIRECTORY.fullmatch(path.name)
        if (
            stage_match is None
            or not 1 <= int(stage_match.group(1)) <= max_generation_round
        ):
            continue
        path_stat = os.lstat(path)
        if not stat.S_ISDIR(path_stat.st_mode):
            raise RuntimeError(
                "rubric generation staging path is not a directory"
            )
        descendants = [path, *path.rglob("*")]
        for descendant in descendants:
            descendant_stat = os.lstat(descendant)
            if not (
                stat.S_ISDIR(descendant_stat.st_mode)
                or stat.S_ISREG(descendant_stat.st_mode)
            ):
                raise RuntimeError(
                    "rubric generation staging tree contains a non-regular entry"
                )
        for descendant in descendants:
            descendant_stat = os.lstat(descendant)
            additions = stat.S_IRUSR | stat.S_IWUSR
            if stat.S_ISDIR(descendant_stat.st_mode):
                additions |= stat.S_IXUSR
            descendant.chmod(stat.S_IMODE(descendant_stat.st_mode) | additions)
        shutil.rmtree(path)
        changed = True
    if changed:
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


