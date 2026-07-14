"""Filesystem primitives for durable submission-revision artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


EXCLUDED_SOLUTION_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "data",
        "instruction.md",
    }
)

LIVE_ROOT_PREFIX = "biomnibench-revision-live-"
_LIVE_ROOT_SENTINEL = ".rubric-gen-live-root.json"


def copy_solution_workspace(source: Path, destination: Path) -> None:
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        if child.name in EXCLUDED_SOLUTION_NAMES:
            continue
        _copy_solution_entry(child, destination / child.name)


def prepare_evaluation_run(submission_dir: Path, evaluation_root: Path) -> Path:
    if os.path.lexists(evaluation_root):
        raise FileExistsError(f"evaluation already exists: {evaluation_root}")
    run_dir = evaluation_root / "run"
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True)
    copy_solution_workspace(submission_dir / "workspace", workspace)
    make_tree_read_only(workspace)
    shutil.copyfile(
        submission_dir / "trajectory.stream.jsonl",
        run_dir / "trajectory.stream.jsonl",
        follow_symlinks=False,
    )
    source_status = read_json_object(
        submission_dir / "status.json",
        "submission status",
    )
    source_status["workspace_dir"] = str(workspace)
    evaluation_trajectory = run_dir / "trajectory.stream.jsonl"
    evaluation_status = run_dir / "status.json"
    write_json(evaluation_status, source_status)
    make_read_only(evaluation_trajectory)
    make_read_only(evaluation_status)
    return run_dir


def verify_submission_snapshot(submission_dir: Path) -> None:
    snapshot = read_json_object(submission_dir / "snapshot.json", "submission snapshot")
    if snapshot.get("submission_id") != submission_dir.name:
        raise RuntimeError("submission snapshot has a mismatched identity")
    if snapshot.get("workspace_sha256") != tree_sha256(submission_dir / "workspace"):
        raise RuntimeError("submission workspace changed after snapshotting")
    if snapshot.get("trajectory_sha256") != sha256_file(
        submission_dir / "trajectory.stream.jsonl"
    ):
        raise RuntimeError("submission trajectory changed after snapshotting")


def tree_sha256(root: Path) -> str:
    return _hash_tree(root, excluded_names=frozenset())


def solution_tree_sha256(root: Path) -> str:
    return _hash_tree(root, excluded_names=EXCLUDED_SOLUTION_NAMES)


def make_tree_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        make_read_only(path)


def make_read_only(path: Path) -> None:
    path.chmod(stat.S_IMODE(os.lstat(path).st_mode) & ~0o222)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(
                json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def write_live_root_sentinel(root: Path, experiment_dir: Path) -> None:
    write_json(
        root / _LIVE_ROOT_SENTINEL,
        {
            "schema_version": 1,
            "kind": "rubric-gen-submission-revision-live-root",
            "experiment_dir": str(experiment_dir.resolve()),
        },
    )
    make_read_only(root / _LIVE_ROOT_SENTINEL)


def remove_live_tree(root: Path, experiment_dir: Path) -> None:
    if not os.path.lexists(root):
        return
    validate_live_root(root, experiment_dir)
    _force_remove_directory(root)


def remove_created_live_tree(root: Path) -> None:
    """Remove a freshly created live root before its sentinel is durable."""
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        root.is_symlink()
        or not root.is_dir()
        or not root.name.startswith(LIVE_ROOT_PREFIX)
        or root.parent.resolve() != temp_root
    ):
        raise RuntimeError(f"invalid new live revision root: {root}")
    _force_remove_directory(root)


def remove_owned_evaluation_tree(root: Path, evaluations_dir: Path) -> None:
    if not os.path.lexists(root):
        return
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"invalid optimizer evaluation root: {root}")
    base = evaluations_dir.absolute()
    candidate = root.absolute()
    try:
        relative = candidate.relative_to(base)
    except ValueError as exc:
        raise RuntimeError(
            f"optimizer evaluation escaped its artifact root: {root}"
        ) from exc
    if len(relative.parts) != 3 or any(
        path.is_symlink()
        for path in (
            base,
            base / relative.parts[0],
            base / relative.parts[0] / relative.parts[1],
        )
    ):
        raise RuntimeError(f"optimizer evaluation escaped its artifact root: {root}")
    _force_remove_directory(root)


def read_json_object(path: Path, context: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{context} is not valid JSON: {path}") from exc
    if type(value) is not dict:
        raise RuntimeError(f"{context} must be a JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _copy_solution_entry(source: Path, destination: Path) -> None:
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        destination.mkdir()
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            _copy_solution_entry(child, destination / child.name)
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a special file: {source}")
    shutil.copyfile(source, destination, follow_symlinks=False)


def _hash_tree(root: Path, *, excluded_names: frozenset[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if Path(relative).parts[0] in excluded_names:
            continue
        path_stat = os.lstat(path)
        if stat.S_ISDIR(path_stat.st_mode):
            digest.update(b"D\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise RuntimeError(f"snapshot contains a non-regular file: {relative}")
        raw = path.read_bytes()
        digest.update(b"F\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def validate_live_root(root: Path, experiment_dir: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        root.is_symlink()
        or not root.is_dir()
        or not root.name.startswith(LIVE_ROOT_PREFIX)
        or root.parent.resolve() != temp_root
    ):
        raise RuntimeError(f"invalid live revision root: {root}")
    sentinel = root / _LIVE_ROOT_SENTINEL
    if sentinel.is_symlink() or not sentinel.is_file():
        raise RuntimeError(f"live revision root sentinel is missing: {root}")
    payload = read_json_object(sentinel, "live revision root sentinel")
    if payload != {
        "schema_version": 1,
        "kind": "rubric-gen-submission-revision-live-root",
        "experiment_dir": str(experiment_dir.resolve()),
    }:
        raise RuntimeError(f"live revision root sentinel does not match: {root}")


def _force_remove_directory(root: Path) -> None:
    directories = [
        path for path in root.rglob("*") if not path.is_symlink() and path.is_dir()
    ]
    for path in [
        *sorted(directories, key=lambda item: len(item.parts), reverse=True),
        root,
    ]:
        path.chmod(stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRWXU)
    shutil.rmtree(root)
    if os.path.lexists(root):
        raise RuntimeError(f"failed to remove owned directory tree: {root}")
