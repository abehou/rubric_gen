"""Atomic publication for rubric-evolution generation artifacts."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from rubric_gen.submission_revision.artifacts import make_read_only


_GENERATION_FILES = frozenset({
    "artifact-history.json",
    "difference-proposal.json",
    "criterion-proposal.json",
    "criterion-edit.json",
    "generation.json",
})


def publish_generation(
    output_dir: Path,
    generation_round: int,
    files: dict[str, str],
) -> None:
    """Publish one immutable generation or validate its exact existing copy."""

    if set(files) != _GENERATION_FILES:
        raise ValueError("rubric generation publication has invalid files")
    root = output_dir / f"bank-{generation_round:04d}"
    if os.path.lexists(root):
        _validate_generation_directory(root, files)
        return
    stage = Path(tempfile.mkdtemp(
        prefix=f".bank-{generation_round:04d}.",
        dir=output_dir,
    ))
    try:
        for name, content in files.items():
            (stage / name).write_text(content, encoding="utf-8")
        _validate_generation_directory(stage, files)
        for path in stage.iterdir():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
            make_read_only(path)
        stage_fd = os.open(stage, os.O_RDONLY)
        try:
            os.fsync(stage_fd)
        finally:
            os.close(stage_fd)
        make_read_only(stage)
        os.rename(stage, root)
        parent_fd = os.open(output_dir, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        if stage.exists():
            for path in stage.iterdir():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
            stage.chmod(0o700)
            shutil.rmtree(stage)
        raise


def _validate_generation_directory(
    root: Path,
    expected_files: dict[str, str],
) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("rubric generation directory is invalid")
    entries = list(root.iterdir())
    if {path.name for path in entries} != _GENERATION_FILES:
        raise RuntimeError("rubric generation directory has invalid files")
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("rubric generation contains a non-regular file")
        try:
            actual = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise RuntimeError("rubric generation file is unreadable") from exc
        if actual != expected_files[path.name]:
            raise RuntimeError(f"rubric generation file changed: {path.name}")
