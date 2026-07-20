"""Filesystem primitives for durable submission-revision artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

from rubric_gen.biomnibench.utils.hashing import sha256_file, sha256_text


EXCLUDED_SOLUTION_NAMES = frozenset(
    {
        ".git",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".uv_cache",
        ".venv",
        "__pycache__",
        "data",
        "instruction.md",
    }
)

LIVE_ROOT_PREFIX = "biomnibench-revision-live-"
LIVE_ROOT_ENV = "BIOMNIBENCH_LIVE_ROOT"
REVISION_EXPERIMENT_KIND = "rubric-gen-submission-revision-experiment"
_LIVE_ROOT_SENTINEL = ".rubric-gen-live-root.json"
_LEGACY_REVISION_MANIFEST_KEYS = frozenset(
    {
        "allow_web",
        "approval_mode",
        "data_sha256",
        "effective_solver_model",
        "executable",
        "feedback_policy",
        "instruction_sha256",
        "judge_model",
        "live_workspace_dir",
        "live_workspace_removed",
        "max_review_chars",
        "model",
        "provider",
        "review",
        "revision_rounds",
        "rubric_name",
        "rubric_set",
        "rubric_sha256",
        "sandbox_requested",
        "schema_version",
        "scoring_identity",
        "session_id",
        "skip_trust",
        "submission_count",
        "task_dir",
        "task_id",
    }
)
_PRE_MITIGATION_REVISION_MANIFEST_KEYS = _LEGACY_REVISION_MANIFEST_KEYS | {"kind"}
_MITIGATION_LEGACY_REVISION_MANIFEST_KEYS = _LEGACY_REVISION_MANIFEST_KEYS | {
    "mitigation"
}
_REVISION_MANIFEST_KEYS = _PRE_MITIGATION_REVISION_MANIFEST_KEYS | {"mitigation"}


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
    temp_root = live_root_parent()
    if (
        root.is_symlink()
        or not root.is_dir()
        or not root.name.startswith(LIVE_ROOT_PREFIX)
        or root.parent.resolve() != temp_root
    ):
        raise RuntimeError(f"invalid new live revision root: {root}")
    _force_remove_directory(root)


def remove_revision_experiment(experiment_dir: Path, task_dir: Path) -> None:
    """Remove an owned revision experiment and any retained live workspace."""

    if experiment_dir.is_symlink() or not experiment_dir.is_dir():
        raise RuntimeError(f"invalid revision experiment directory: {experiment_dir}")
    manifest_path = experiment_dir / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(
            f"restart requires a valid revision manifest: {manifest_path}"
        )
    manifest = read_json_object(manifest_path, "revision manifest")
    manifest_keys = set(manifest)
    is_current_manifest = (
        manifest_keys == _REVISION_MANIFEST_KEYS
        and manifest.get("kind") == REVISION_EXPERIMENT_KIND
    )
    if (
        not is_current_manifest
        and manifest_keys != _PRE_MITIGATION_REVISION_MANIFEST_KEYS
        and manifest_keys != _MITIGATION_LEGACY_REVISION_MANIFEST_KEYS
        and manifest_keys != _LEGACY_REVISION_MANIFEST_KEYS
    ):
        raise RuntimeError(
            f"restart requires a valid revision manifest: {manifest_path}"
        )
    expected_task_dir = task_dir.resolve()
    revision_rounds = manifest.get("revision_rounds")
    submission_count = manifest.get("submission_count")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("task_id") != expected_task_dir.name
        or manifest.get("task_dir") != str(expected_task_dir)
        or type(revision_rounds) is not int
        or revision_rounds < 0
        or type(submission_count) is not int
        or submission_count != revision_rounds + 1
        or type(manifest.get("scoring_identity")) is not dict
    ):
        raise RuntimeError("restart experiment does not belong to the requested task")
    workspace_value = manifest.get("live_workspace_dir")
    if type(workspace_value) is not str:
        raise RuntimeError("restart experiment has no valid live workspace path")
    workspace = Path(workspace_value)
    if not workspace.is_absolute() or workspace.name != "workspace":
        raise RuntimeError("restart experiment has an invalid live workspace path")
    live_root = workspace.parent
    live_workspace_removed = manifest.get("live_workspace_removed")
    if type(live_workspace_removed) is not bool:
        raise RuntimeError("restart experiment has an invalid live workspace state")
    live_root_exists = os.path.lexists(live_root)
    if live_workspace_removed and live_root_exists:
        raise RuntimeError("completed restart experiment unexpectedly has a live root")
    if live_root_exists:
        remove_live_tree(live_root, experiment_dir)
    _force_remove_directory(experiment_dir)


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
    temp_root = live_root_parent()
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


def live_root_parent() -> Path:
    configured = os.environ.get(LIVE_ROOT_ENV)
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            raise RuntimeError(f"{LIVE_ROOT_ENV} must be an absolute path")
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(f"invalid {LIVE_ROOT_ENV}: {root}")
        return root.resolve()
    return Path(tempfile.gettempdir()).resolve()


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
