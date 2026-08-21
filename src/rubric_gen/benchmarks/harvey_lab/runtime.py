"""Private runtime storage for Harvey LAB workflows."""

from __future__ import annotations

import os
import stat
import threading
from collections.abc import Mapping
from pathlib import Path


RUNTIME_ROOT_ENV = "HARVEY_RUNTIME_ROOT"
_RUNTIME_DIRECTORY_LOCK = threading.Lock()


def runtime_root_from_environment(
    source: Mapping[str, str] | None = None,
) -> Path:
    """Return the required private Harvey runtime root."""

    environment = os.environ if source is None else source
    configured = environment.get(RUNTIME_ROOT_ENV)
    if not configured:
        raise RuntimeError(
            f"Harvey requires {RUNTIME_ROOT_ENV} for private runtime storage"
        )
    return ensure_runtime_root(Path(configured))


def ensure_runtime_root(root: Path) -> Path:
    """Create or validate one private, user-owned runtime root."""

    with _RUNTIME_DIRECTORY_LOCK:
        return _ensure_runtime_root(root)


def _ensure_runtime_root(root: Path) -> Path:
    if not root.is_absolute():
        raise RuntimeError(f"Harvey runtime root must be absolute: {root}")
    if not os.path.lexists(root):
        try:
            resolved_parent = root.parent.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(
                f"Harvey runtime root parent is not accessible: {root.parent}"
            ) from exc
        if resolved_parent != root.parent:
            raise RuntimeError(
                "Harvey runtime root must not contain symbolic-link components: "
                f"{root}"
            )
        try:
            root.mkdir(mode=stat.S_IRWXU)
            root.chmod(stat.S_IRWXU)
        except FileExistsError:
            pass
        except OSError as exc:
            raise RuntimeError(f"Harvey runtime root cannot be created: {root}") from exc
    return _validate_private_directory(root, "Harvey runtime root")


def ensure_runtime_directory(root: Path, name: str) -> Path:
    """Create or validate one private direct child of the runtime root."""

    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError(f"invalid Harvey runtime directory name: {name!r}")
    with _RUNTIME_DIRECTORY_LOCK:
        validated_root = _ensure_runtime_root(root)
        directory = validated_root / name
        if not os.path.lexists(directory):
            try:
                directory.mkdir(mode=stat.S_IRWXU)
                directory.chmod(stat.S_IRWXU)
            except FileExistsError:
                pass
            except OSError as exc:
                raise RuntimeError(
                    f"Harvey runtime directory cannot be created: {directory}"
                ) from exc
        validated = _validate_private_directory(
            directory,
            "Harvey runtime directory",
        )
        if validated.parent != validated_root:
            raise RuntimeError(
                f"Harvey runtime directory escaped its root: {directory}"
            )
        return validated


def _validate_private_directory(path: Path, label: str) -> Path:
    try:
        details = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"{label} is not accessible: {path}") from exc
    if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
        raise RuntimeError(f"{label} must be a regular directory: {path}")
    if details.st_uid != os.getuid():
        raise RuntimeError(f"{label} must be owned by this user: {path}")
    if stat.S_IMODE(details.st_mode) != stat.S_IRWXU:
        raise RuntimeError(f"{label} must have mode 0700: {path}")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(f"{label} cannot be resolved: {path}") from exc
    if resolved != path:
        raise RuntimeError(
            f"{label} must not contain symbolic-link components: {path}"
        )
    if not os.access(path, os.W_OK | os.X_OK):
        raise RuntimeError(f"{label} is not writable: {path}")
    return path
