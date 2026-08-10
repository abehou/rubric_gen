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

from rubric_gen.biomnibench.utils.hashing import sha256_file, sha256_text
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT


EXCLUDED_SOLUTION_NAMES = frozenset(
    {
        ".git",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".uv-cache",
        ".uv_cache",
        ".venv",
        "__pycache__",
        "data",
        "instruction.md",
        "packages",
        "venv",
    }
)
RETAINED_HISTORICAL_SOLUTION_NAMES = frozenset({"answer.txt", "trace.md"})

LIVE_ROOT_PREFIX = "biomnibench-revision-live-"
LIVE_ROOT_ENV = "BIOMNIBENCH_LIVE_ROOT"
REVISION_EXPERIMENT_KIND = "rubric-gen-submission-revision-experiment"
_LIVE_ROOT_SENTINEL = ".rubric-gen-live-root.json"
REVISION_MANIFEST_KEYS = frozenset(
    {
        "assignment_id",
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
        "judge_base_url",
        "judge_max_retries",
        "judge_model",
        "kind",
        "live_workspace_dir",
        "live_workspace_removed",
        "max_review_chars",
        "model",
        "prompt",
        "provider",
        "reasoning_effort",
        "replicate",
        "review",
        "revision_rounds",
        "rubric_evolution",
        "rubric_name",
        "rubric_proposer_model",
        "rubric_proposer_base_url",
        "rubric_proposer_max_retries",
        "rubric_proposer_step_limit",
        "rubric_set",
        "rubric_sha256",
        "schema_version",
        "scoring_identity",
        "seed_run_dir",
        "seed_sha256",
        "service_tier",
        "session_id",
        "submission_count",
        "task_dir",
        "task_id",
        "turn_timeout_seconds",
        "web_search",
    }
)


def revision_manifest_keys(feedback_policy: str) -> frozenset[str]:
    """Return the strict manifest shape for one feedback protocol."""

    if feedback_policy == "simulated_user":
        return REVISION_MANIFEST_KEYS | {"feedback_simulator"}
    return REVISION_MANIFEST_KEYS


@dataclass
class SnapshotCopyStats:
    copied_files: int = 0
    copied_bytes: int = 0
    linked_files: int = 0
    linked_bytes: int = 0

    @property
    def logical_bytes(self) -> int:
        return self.copied_bytes + self.linked_bytes


@dataclass
class WorkspaceCompactionStats:
    removed_files: int = 0
    removed_logical_bytes: int = 0


def copy_solution_workspace(
    source: Path,
    destination: Path,
    *,
    previous: Path | None = None,
) -> SnapshotCopyStats:
    """Snapshot a solution, hard-linking files unchanged from the prior round."""
    if previous is not None and (previous.is_symlink() or not previous.is_dir()):
        raise RuntimeError(f"invalid previous solution snapshot: {previous}")
    stats = SnapshotCopyStats()
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        if is_excluded_solution_root(child):
            continue
        previous_child = previous / child.name if previous is not None else None
        _copy_solution_entry(
            child,
            destination / child.name,
            previous_child,
            stats,
        )
    return stats


def compact_historical_workspace(root: Path) -> WorkspaceCompactionStats:
    """Retain only immutable judge inputs in a historical workspace snapshot."""
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"invalid historical solution snapshot: {root}")
    stats = WorkspaceCompactionStats()
    root.chmod(stat.S_IMODE(os.lstat(root).st_mode) | stat.S_IRWXU)
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if child.name in RETAINED_HISTORICAL_SOLUTION_NAMES:
            child_stat = os.lstat(child)
            if not stat.S_ISREG(child_stat.st_mode):
                raise RuntimeError(
                    f"retained historical artifact is not a regular file: {child}"
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
    make_tree_read_only(root)
    return stats


def prepare_evaluation_run(submission_dir: Path, evaluation_root: Path) -> Path:
    if os.path.lexists(evaluation_root):
        raise FileExistsError(f"evaluation already exists: {evaluation_root}")
    run_dir = evaluation_root / "run"
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True)
    _link_solution_workspace(submission_dir / "workspace", workspace)
    make_tree_read_only(workspace)
    os.link(
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


def link_solution_workspace(source: Path, destination: Path) -> None:
    """Hardlink an immutable solution tree without duplicating file contents."""
    _link_solution_workspace(source, destination)


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
    return _hash_tree(root, excluded_names=frozenset())


def solution_tree_sha256(root: Path) -> str:
    excluded_names = EXCLUDED_SOLUTION_NAMES | frozenset(
        child.name
        for child in root.iterdir()
        if is_excluded_solution_root(child)
    )
    return _hash_tree(root, excluded_names=excluded_names)


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


def _copy_solution_entry(
    source: Path,
    destination: Path,
    previous: Path | None,
    stats: SnapshotCopyStats,
) -> None:
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        destination.mkdir()
        previous_dir = (
            previous
            if previous is not None
            and not previous.is_symlink()
            and previous.is_dir()
            else None
        )
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            _copy_solution_entry(
                child,
                destination / child.name,
                previous_dir / child.name if previous_dir is not None else None,
                stats,
            )
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a special file: {source}")
    if (
        previous is not None
        and not previous.is_symlink()
        and previous.is_file()
        and _regular_files_equal(source, previous)
    ):
        os.link(previous, destination, follow_symlinks=False)
        stats.linked_files += 1
        stats.linked_bytes += source_stat.st_size
        return
    shutil.copyfile(source, destination, follow_symlinks=False)
    stats.copied_files += 1
    stats.copied_bytes += source_stat.st_size


def _regular_files_equal(first: Path, second: Path) -> bool:
    first_stat = os.lstat(first)
    second_stat = os.lstat(second)
    if not stat.S_ISREG(second_stat.st_mode) or first_stat.st_size != second_stat.st_size:
        return False
    with first.open("rb") as first_stream, second.open("rb") as second_stream:
        while True:
            first_chunk = first_stream.read(1024 * 1024)
            second_chunk = second_stream.read(1024 * 1024)
            if first_chunk != second_chunk:
                return False
            if not first_chunk:
                return True


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


def _link_solution_workspace(source: Path, destination: Path) -> None:
    """Mirror an immutable snapshot without duplicating regular-file contents."""
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError(f"invalid submission workspace: {source}")
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        _link_solution_entry(child, destination / child.name)


def _link_solution_entry(source: Path, destination: Path) -> None:
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"submission snapshot contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        destination.mkdir()
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            _link_solution_entry(child, destination / child.name)
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"submission snapshot contains a special file: {source}")
    os.link(source, destination, follow_symlinks=False)


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
        "schema_version": 1,
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
            / "biomnibench-live"
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
