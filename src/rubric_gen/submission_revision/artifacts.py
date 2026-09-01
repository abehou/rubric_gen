"""Filesystem primitives for durable submission-revision artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.runtime.paths import PROJECT_ROOT
from rubric_gen.submission_revision.rubrics.schema import load_json_strict


RECURSIVE_EXCLUDED_SOLUTION_NAMES = frozenset(
    {
        ".agent-tmp",
        ".cache",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        ".uv_cache",
        ".venv",
        "__pycache__",
        "venv",
    }
)
EXCLUDED_SOLUTION_NAMES = RECURSIVE_EXCLUDED_SOLUTION_NAMES | frozenset(
    {"data", "instruction.md", "packages"}
)
RETAINED_HISTORICAL_SOLUTION_NAMES = frozenset({"answer.txt", "trace.md"})

LIVE_ROOT_PREFIX = "submission-revision-live-"
LIVE_ROOT_ENV = "BIOMNIBENCH_LIVE_ROOT"
REVISION_EXPERIMENT_KIND = "rubric-gen-submission-revision-experiment"
_LIVE_ROOT_SENTINEL = ".rubric-gen-live-root.json"
REVISION_MANIFEST_KEYS = frozenset(
    {
        "assignment_id",
        "benchmark",
        "command_network_access",
        "condition_id",
        "data_sha256",
        "experiment_id",
        "effective_solver_model",
        "executable",
        "execution_order",
        "feedback_policy",
        "instruction_sha256",
        "isolation",
        "judge_model",
        "kind",
        "live_workspace_dir",
        "live_workspace_removed",
        "max_review_chars",
        "model",
        "master_rubric_name",
        "master_rubric_sha256",
        "initial_rubric_path",
        "initial_generation_sha256",
        "initial_rubric_sha256",
        "prompt",
        "provider",
        "reasoning_effort",
        "replicate",
        "elicitation_seed_replicates",
        "review",
        "max_revisions",
        "min_revisions",
        "rubric_policy",
        "rubric_proposer_model",
        "rubric_proposer_max_retries",
        "rubric_generation_implementation_sha256",
        "initial_scoring_identity",
        "seed_run_dir",
        "pretreatment_rubric_dir",
        "seed_sha256",
        "service_tier",
        "session_id",
        "seed_generator",
        "solver_id",
        "submission_count",
        "task_dir",
        "task_id",
        "turn_timeout_seconds",
        "web_search",
    }
)


def revision_manifest_keys(feedback_policy: str) -> frozenset[str]:
    """Return the strict manifest shape for one feedback protocol."""

    if feedback_policy == "user_simulator":
        return REVISION_MANIFEST_KEYS | {"feedback_simulator"}
    return REVISION_MANIFEST_KEYS


@dataclass
class WorkspaceSnapshotStats:
    files: int = 0
    bytes: int = 0


@dataclass
class WorkspaceCompactionStats:
    removed_files: int = 0
    removed_logical_bytes: int = 0


def snapshot_solution_workspace(
    source: Path,
    destination: Path,
) -> WorkspaceSnapshotStats:
    """Copy a live solution into an independent, read-only snapshot."""
    stats = WorkspaceSnapshotStats()
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        if is_excluded_solution_root(child):
            continue
        _copy_solution_entry(
            child,
            destination / child.name,
            stats,
        )
    make_read_only(destination)
    return stats


def compact_historical_workspace(
    root: Path,
    *,
    retained_names: frozenset[str] = RETAINED_HISTORICAL_SOLUTION_NAMES,
) -> WorkspaceCompactionStats:
    """Retain only immutable judge inputs in a historical workspace snapshot."""
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"invalid historical solution snapshot: {root}")
    stats = WorkspaceCompactionStats()
    root.chmod(stat.S_IMODE(os.lstat(root).st_mode) | stat.S_IRWXU)
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.name in retained_names:
            child_stat = os.lstat(child)
            if not (
                stat.S_ISREG(child_stat.st_mode)
                or stat.S_ISDIR(child_stat.st_mode)
            ):
                raise RuntimeError(
                    f"retained historical artifact is not regular: {child}"
                )
            continue
        removed_files, removed_bytes = _tree_file_totals(child)
        if child.is_symlink():
            raise RuntimeError(
                f"historical solution snapshot contains a symlink: {child}"
            )
        if child.is_dir():
            _force_remove_directory(child)
        elif child.is_file():
            child.chmod(stat.S_IMODE(os.lstat(child).st_mode) | stat.S_IWUSR)
            child.unlink()
        else:
            raise RuntimeError(
                f"historical solution snapshot contains a special file: {child}"
            )
        stats.removed_files += removed_files
        stats.removed_logical_bytes += removed_bytes
    _seal_compacted_tree(root)
    return stats


def prepare_evaluation_run(submission_dir: Path, evaluation_root: Path) -> Path:
    if os.path.lexists(evaluation_root):
        raise FileExistsError(f"evaluation already exists: {evaluation_root}")
    run_dir = evaluation_root / "run"
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True)
    copy_immutable_workspace(submission_dir / "workspace", workspace)
    copy_immutable_file(
        submission_dir / "trajectory.stream.jsonl",
        run_dir / "trajectory.stream.jsonl",
    )
    source_status = read_json_object(
        submission_dir / "status.json",
        "submission status",
    )
    source_status["workspace_dir"] = str(workspace)
    evaluation_status = run_dir / "status.json"
    write_json(evaluation_status, source_status)
    return run_dir


def copy_immutable_workspace(source: Path, destination: Path) -> None:
    """Copy a sealed solution tree without sharing mutable inode metadata."""
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError(f"invalid immutable workspace: {source}")
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        _copy_immutable_entry(child, destination / child.name)
    make_read_only(destination)


def copy_immutable_file(source: Path, destination: Path) -> None:
    """Copy one sealed file into an inode-independent sealed file."""
    source_stat = os.lstat(source)
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_mode & 0o222:
        raise RuntimeError(f"immutable source is not a read-only file: {source}")
    shutil.copyfile(source, destination, follow_symlinks=False)
    make_read_only(destination)


def verify_submission_snapshot(submission_dir: Path) -> None:
    if submission_dir.is_symlink() or not submission_dir.is_dir():
        raise RuntimeError(f"invalid submission snapshot directory: {submission_dir}")
    for path, label, directory in (
        (submission_dir / "snapshot.json", "snapshot metadata", False),
        (submission_dir / "status.json", "submission status", False),
        (submission_dir / "trajectory.stream.jsonl", "submission trajectory", False),
        (submission_dir / "workspace", "submission workspace", True),
    ):
        try:
            path_stat = os.lstat(path)
        except OSError as exc:
            raise RuntimeError(f"missing {label}: {path}") from exc
        expected = stat.S_ISDIR(path_stat.st_mode) if directory else stat.S_ISREG(
            path_stat.st_mode
        )
        if not expected:
            raise RuntimeError(f"invalid {label}: {path}")
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
    return _hash_tree(
        root,
        excluded_names=frozenset(),
        recursive_excluded_names=frozenset(),
    )


def solution_tree_sha256(root: Path) -> str:
    excluded_names = EXCLUDED_SOLUTION_NAMES | frozenset(
        child.name
        for child in root.iterdir()
        if is_excluded_solution_root(child)
    )
    return _hash_tree(
        root,
        excluded_names=excluded_names,
        recursive_excluded_names=RECURSIVE_EXCLUDED_SOLUTION_NAMES,
    )


def is_excluded_solution_root(path: Path) -> bool:
    """Return whether a top-level workspace entry is disposable run state."""
    if path.name in EXCLUDED_SOLUTION_NAMES:
        return True
    try:
        path_stat = os.lstat(path)
        marker = path / "pyvenv.cfg"
        marker_stat = os.lstat(marker)
    except OSError:
        return False
    return stat.S_ISDIR(path_stat.st_mode) and stat.S_ISREG(marker_stat.st_mode)


def make_tree_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        make_read_only(path)


def make_tree_owner_writable(root: Path) -> None:
    """Make directories and regular files in a private live tree writable."""
    for path in [root, *root.rglob("*")]:
        path_stat = os.lstat(path)
        if stat.S_ISLNK(path_stat.st_mode):
            continue
        if stat.S_ISDIR(path_stat.st_mode):
            additions = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
        elif stat.S_ISREG(path_stat.st_mode):
            additions = stat.S_IRUSR | stat.S_IWUSR
        else:
            continue
        path.chmod(stat.S_IMODE(path_stat.st_mode) | additions)


def make_read_only(path: Path) -> None:
    path.chmod(stat.S_IMODE(os.lstat(path).st_mode) & ~0o222)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_live_root_sentinel(root: Path, experiment_dir: Path) -> None:
    write_json(
        root / _LIVE_ROOT_SENTINEL,
        {
            "kind": "rubric-gen-submission-revision-live-root",
            "experiment_dir": str(experiment_dir.resolve()),
        },
    )


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
        value = load_json_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"{context} is not valid JSON: {path}") from exc
    if type(value) is not dict:
        raise RuntimeError(f"{context} must be a JSON object: {path}")
    return value


def _copy_solution_entry(
    source: Path,
    destination: Path,
    stats: WorkspaceSnapshotStats,
) -> None:
    if source.name in RECURSIVE_EXCLUDED_SOLUTION_NAMES:
        return
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        destination.mkdir()
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            _copy_solution_entry(
                child,
                destination / child.name,
                stats,
            )
        make_read_only(destination)
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a special file: {source}")
    shutil.copyfile(source, destination, follow_symlinks=False)
    make_read_only(destination)
    stats.files += 1
    stats.bytes += source_stat.st_size


def _tree_file_totals(root: Path) -> tuple[int, int]:
    root_stat = os.lstat(root)
    if stat.S_ISLNK(root_stat.st_mode):
        raise RuntimeError(f"historical solution snapshot contains a symlink: {root}")
    if stat.S_ISREG(root_stat.st_mode):
        return 1, root_stat.st_size
    if not stat.S_ISDIR(root_stat.st_mode):
        raise RuntimeError(
            f"historical solution snapshot contains a special file: {root}"
        )
    files = 0
    logical_bytes = 0
    for child in root.iterdir():
        child_files, child_bytes = _tree_file_totals(child)
        files += child_files
        logical_bytes += child_bytes
    return files, logical_bytes


def _copy_immutable_entry(source: Path, destination: Path) -> None:
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"immutable workspace contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        destination.mkdir()
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            _copy_immutable_entry(child, destination / child.name)
        make_read_only(destination)
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"immutable workspace contains a special file: {source}")
    copy_immutable_file(source, destination)


def _seal_compacted_tree(root: Path) -> None:
    """Seal an inode-independent compacted tree and reject unsafe entries."""
    for path in [*root.rglob("*"), root]:
        path_stat = os.lstat(path)
        if stat.S_ISDIR(path_stat.st_mode) or stat.S_ISREG(path_stat.st_mode):
            make_read_only(path)
        elif stat.S_ISLNK(path_stat.st_mode):
            raise RuntimeError(f"immutable snapshot contains a symlink: {path}")
        else:
            raise RuntimeError(f"immutable snapshot contains a special file: {path}")


def _hash_tree(
    root: Path,
    *,
    excluded_names: frozenset[str],
    recursive_excluded_names: frozenset[str],
) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        if (
            relative_path.parts[0] in excluded_names
            or any(
                part in recursive_excluded_names
                for part in relative_path.parts[1:]
            )
        ):
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
    allowed_parents = {
        Path(tempfile.gettempdir()).resolve(),
        live_root_parent(),
    }
    if (
        root.is_symlink()
        or not root.is_dir()
        or not root.name.startswith(LIVE_ROOT_PREFIX)
        or root.parent.resolve() not in allowed_parents
    ):
        raise RuntimeError(f"invalid live revision root: {root}")
    sentinel = root / _LIVE_ROOT_SENTINEL
    if sentinel.is_symlink() or not sentinel.is_file():
        raise RuntimeError(f"live revision root sentinel is missing: {root}")
    payload = read_json_object(sentinel, "live revision root sentinel")
    if payload != {
        "kind": "rubric-gen-submission-revision-live-root",
        "experiment_dir": str(experiment_dir.resolve()),
    }:
        raise RuntimeError(f"live revision root sentinel does not match: {root}")


def live_root_parent() -> Path:
    configured = os.environ.get(LIVE_ROOT_ENV)
    source = LIVE_ROOT_ENV
    if not configured:
        configured = str(
            Path(tempfile.gettempdir())
            / f"rubric-gen-{os.getuid()}"
            / "submission-live"
        )
        source = "system temporary default"
    root = Path(configured).expanduser()
    if not root.is_absolute():
        raise RuntimeError(f"{source} must be an absolute path")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"invalid revision live root from {source}: {root}")
    resolved = root.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return resolved
    raise RuntimeError(
        f"{source} must be outside the repository to prevent cross-run reads"
    )


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
