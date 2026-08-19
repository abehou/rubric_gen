"""Validated, content-addressed artifacts for Harvey experiments."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic


def read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def validate_regular_tree(root: Path, label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"{label} must be a regular directory: {root}")
    for path in root.rglob("*"):
        mode = os.lstat(path).st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError(f"{label} contains a link or special file: {path}")


def tree_sha256(root: Path) -> str:
    validate_regular_tree(root, "artifact tree")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        mode = os.lstat(path).st_mode
        kind = b"d" if stat.S_ISDIR(mode) else b"f"
        digest.update(kind + b"\0" + relative.encode("utf-8") + b"\0")
        if stat.S_ISREG(mode):
            digest.update(b"x" if mode & 0o111 else b"-")
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_regular_tree(source: Path, destination: Path) -> None:
    validate_regular_tree(source, "source tree")
    if os.path.lexists(destination):
        raise FileExistsError(f"destination already exists: {destination}")
    shutil.copytree(source, destination)


def make_tree_read_only(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(stat.S_IMODE(os.lstat(path).st_mode) & ~0o222)
    root.chmod(stat.S_IMODE(os.lstat(root).st_mode) & ~0o222)


def validate_checkout(
    checkout: Path,
    revision: str,
    task_ids: tuple[str, ...],
) -> None:
    required = (
        checkout / "harness" / "run.py",
        checkout / "harness" / "system_prompt.md",
        checkout / "evaluation" / "run_eval.py",
        checkout / "sandbox" / "sandbox.py",
        checkout / "utils",
        checkout / "tasks",
        checkout / "pyproject.toml",
    )
    if checkout.is_symlink() or not checkout.is_dir() or any(not path.exists() for path in required):
        raise ValueError(f"benchmark.checkout is not a Harvey LAB checkout: {checkout}")
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0 or result.stdout.strip() != revision:
        observed = result.stdout.strip() or result.stderr.strip() or "unknown"
        raise ValueError(f"Harvey checkout revision is {observed}, expected {revision}")
    tracked_inputs = [
        "harness",
        "evaluation",
        "sandbox",
        "utils",
        "pyproject.toml",
        "uv.lock",
        *(f"tasks/{task_id}" for task_id in task_ids),
    ]
    try:
        dirty = subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "diff",
                "--quiet",
                "--no-ext-diff",
                revision,
                "--",
                *tracked_inputs,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("timed out validating Harvey checkout inputs") from exc
    if dirty.returncode == 1:
        raise ValueError("Harvey checkout has tracked changes; use a clean pinned checkout")
    if dirty.returncode != 0:
        detail = dirty.stderr.strip() or dirty.stdout.strip() or "unknown git error"
        raise ValueError(f"could not validate Harvey checkout inputs: {detail}")
    try:
        untracked = subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "ls-files",
                "--others",
                "--",
                *tracked_inputs,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("timed out validating untracked Harvey checkout inputs") from exc
    if untracked.returncode != 0:
        detail = untracked.stderr.strip() or untracked.stdout.strip() or "unknown git error"
        raise ValueError(f"could not validate untracked Harvey checkout inputs: {detail}")
    if untracked.stdout:
        raise ValueError(
            "Harvey checkout has untracked input files; use a clean pinned checkout"
        )


def task_path(root: Path, task_id: str) -> Path:
    relative = Path(task_id)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) < 2:
        raise ValueError(f"unsafe Harvey task ID: {task_id}")
    path = root / relative
    if path.resolve() != (root.resolve() / relative):
        raise ValueError(f"Harvey task escapes the task root: {task_id}")
    return path


def validate_task(task_file: Path) -> dict[str, object]:
    task = read_json_object(task_file, "Harvey task")
    for key in ("title", "instructions", "criteria"):
        if key not in task:
            raise ValueError(f"Harvey task lacks {key}: {task_file}")
    criteria = task["criteria"]
    if not isinstance(criteria, list) or not criteria:
        raise ValueError(f"Harvey task criteria must be a non-empty list: {task_file}")
    seen: set[str] = set()
    for index, item in enumerate(criteria):
        if not isinstance(item, dict):
            raise ValueError(f"Harvey criterion {index} is not an object: {task_file}")
        for key in ("id", "title", "match_criteria"):
            if type(item.get(key)) is not str or not str(item[key]).strip():
                raise ValueError(f"Harvey criterion {index} has invalid {key}: {task_file}")
        criterion_id = str(item["id"])
        if criterion_id in seen:
            raise ValueError(f"duplicate Harvey criterion ID {criterion_id}: {task_file}")
        seen.add(criterion_id)
        deliverables = item.get("deliverables", [])
        if not isinstance(deliverables, list) or any(type(value) is not str for value in deliverables):
            raise ValueError(f"Harvey criterion {criterion_id} has invalid deliverables")
    return task


def write_identity(path: Path, value: dict[str, object], *, resume: bool) -> None:
    if path.is_file():
        if not resume:
            raise FileExistsError(f"experiment output exists; use --resume: {path.parent}")
        if read_json_object(path, "experiment identity") != value:
            raise ValueError("existing Harvey experiment identity differs from the specification")
        return
    if resume:
        raise ValueError("resumed Harvey experiment has no experiment.json")
    write_json_atomic(path, value)
