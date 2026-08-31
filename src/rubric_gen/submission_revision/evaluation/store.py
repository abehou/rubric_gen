"""Secure output storage for revision evaluation stages."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.artifacts import (
    make_tree_owner_writable,
    read_json_object,
)


class EvaluationStore:
    """Keep stage output inside one symlink-free directory tree."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(os.fspath(root.expanduser())))
        self._validate_path(
            self.root,
            expected="directory",
            allow_missing=True,
        )

    def path(self, *parts: str) -> Path:
        for part in parts:
            if (
                type(part) is not str
                or not part
                or part in {".", ".."}
                or Path(part).name != part
            ):
                raise RuntimeError(f"evaluation output path component is unsafe: {part!r}")
        candidate = self.root.joinpath(*parts)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeError(
                f"evaluation output path escapes its root: {candidate}"
            ) from exc
        self._validate_path(candidate, expected=None, allow_missing=True)
        return candidate

    def prepare(self, identity: dict[str, object], resume: bool) -> None:
        if os.path.lexists(self.root):
            self._validate_path(
                self.root,
                expected="directory",
                allow_missing=False,
            )
            self.validate_tree()
            try:
                manifest_path = self.regular_file("manifest.json")
                manifest = read_json_object(manifest_path, "evaluation manifest")
            except RuntimeError:
                if not resume:
                    raise
                self._replace(identity)
                return
            if manifest != identity:
                if not resume:
                    raise RuntimeError("evaluation resume identity changed")
                self._replace(identity)
                return
            if not resume and any(
                path.name != "manifest.json" for path in self.root.iterdir()
            ):
                raise FileExistsError(
                    f"evaluation output is not empty: {self.root}"
                )
            return
        self._ensure_directory_path(self.root)
        self.write_json(("manifest.json",), identity)

    def _replace(self, identity: dict[str, object]) -> None:
        self.validate_tree()
        make_tree_owner_writable(self.root)
        shutil.rmtree(self.root)
        if os.path.lexists(self.root):
            raise RuntimeError(
                f"failed to replace incompatible evaluation output: {self.root}"
            )
        self._ensure_directory_path(self.root)
        self.write_json(("manifest.json",), identity)

    def ensure_directory(self, *parts: str) -> Path:
        path = self.path(*parts)
        self._ensure_directory_path(path)
        return path

    def regular_file(self, *parts: str, allow_missing: bool = False) -> Path:
        path = self.path(*parts)
        self._validate_path(
            path,
            expected="file",
            allow_missing=allow_missing,
        )
        return path

    def contained_regular_file(self, candidate: Path) -> Path:
        path = Path(os.path.abspath(os.fspath(candidate.expanduser())))
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeError(
                f"evaluation artifact path escapes its root: {candidate}"
            ) from exc
        self._validate_path(path, expected="file", allow_missing=False)
        return path

    def validate_tree(self, *parts: str) -> Path:
        root = self.path(*parts) if parts else self.root
        self._validate_path(root, expected="directory", allow_missing=False)
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as exc:
                raise RuntimeError(
                    f"cannot inspect evaluation output directory: {directory}"
                ) from exc
            for entry in entries:
                path = Path(entry.path)
                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    raise RuntimeError(
                        f"cannot inspect evaluation output path: {path}"
                    ) from exc
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise RuntimeError(
                        f"evaluation output path contains a symlink: {path}"
                    )
                if stat.S_ISDIR(entry_stat.st_mode):
                    pending.append(path)
                elif not stat.S_ISREG(entry_stat.st_mode):
                    raise RuntimeError(f"evaluation output path is not regular: {path}")
        return root

    def write_json(self, parts: tuple[str, ...], value: object) -> Path:
        if not parts:
            raise RuntimeError("evaluation JSON output path is empty")
        self.ensure_directory(*parts[:-1])
        path = self.regular_file(*parts, allow_missing=True)
        write_json_atomic(path, value)
        self._validate_path(path, expected="file", allow_missing=False)
        return path

    @staticmethod
    def _validate_path(
        path: Path,
        *,
        expected: str | None,
        allow_missing: bool,
    ) -> None:
        current = Path(path.anchor)
        parts = path.parts[1:]
        missing = False
        for index, part in enumerate(parts):
            current = current / part
            if missing:
                continue
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError:
                missing = True
                continue
            except OSError as exc:
                raise RuntimeError(
                    f"cannot inspect evaluation output path: {current}"
                ) from exc
            if stat.S_ISLNK(current_stat.st_mode):
                raise RuntimeError(f"evaluation output path contains a symlink: {current}")
            is_last = index == len(parts) - 1
            if not is_last and not stat.S_ISDIR(current_stat.st_mode):
                raise RuntimeError(
                    f"evaluation output path component is not a directory: {current}"
                )
            if is_last and expected == "directory" and not stat.S_ISDIR(
                current_stat.st_mode
            ):
                raise RuntimeError(
                    f"evaluation output path is not a directory: {current}"
                )
            if is_last and expected == "file" and not stat.S_ISREG(
                current_stat.st_mode
            ):
                raise RuntimeError(
                    f"evaluation output path is not a regular file: {current}"
                )
        if missing and not allow_missing:
            raise RuntimeError(f"evaluation output path is missing: {path}")

    @classmethod
    def _ensure_directory_path(cls, path: Path) -> None:
        current = Path(path.anchor)
        for part in path.parts[1:]:
            current = current / part
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError:
                try:
                    current.mkdir()
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise RuntimeError(
                        f"cannot create evaluation output directory: {current}"
                    ) from exc
                try:
                    current_stat = os.lstat(current)
                except OSError as exc:
                    raise RuntimeError(
                        f"cannot inspect evaluation output directory: {current}"
                    ) from exc
            except OSError as exc:
                raise RuntimeError(
                    f"cannot inspect evaluation output path: {current}"
                ) from exc
            if stat.S_ISLNK(current_stat.st_mode):
                raise RuntimeError(f"evaluation output path contains a symlink: {current}")
            if not stat.S_ISDIR(current_stat.st_mode):
                raise RuntimeError(
                    f"evaluation output path component is not a directory: {current}"
                )
