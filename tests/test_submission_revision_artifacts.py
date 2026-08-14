from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from rubric_gen.submission_revision.artifacts import (
    compact_historical_workspace,
    copy_solution_workspace,
    make_tree_read_only,
    prepare_evaluation_run,
    solution_tree_sha256,
)


def test_solution_snapshot_excludes_disposable_local_uv_cache(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer\n")
    (workspace / "trace.md").write_text("trace\n")
    cache_target = tmp_path / "bulk-cache"
    cache_target.mkdir()
    (workspace / ".uv_cache").symlink_to(cache_target, target_is_directory=True)

    digest = solution_tree_sha256(workspace)
    snapshot = tmp_path / "snapshot"
    copy_solution_workspace(workspace, snapshot)

    assert len(digest) == 64
    assert not (snapshot / ".uv_cache").exists()
    assert (snapshot / "answer.txt").read_text() == "answer\n"


def test_solution_snapshot_deduplicates_unchanged_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer-0\n")
    (workspace / "large-result.bin").write_bytes(b"result" * 1024)
    (workspace / "nested").mkdir()
    (workspace / "nested" / "stable.csv").write_text("x\n1\n")
    first = tmp_path / "s000"

    first_stats = copy_solution_workspace(workspace, first)
    (workspace / "answer.txt").write_text("answer-1\n")
    second = tmp_path / "s001"
    second_stats = copy_solution_workspace(workspace, second, previous=first)

    assert first_stats.linked_files == 0
    assert second_stats.copied_files == 1
    assert second_stats.linked_files == 2
    assert second_stats.linked_bytes == len(b"result" * 1024) + len("x\n1\n")
    assert (first / "large-result.bin").stat().st_ino == (
        second / "large-result.bin"
    ).stat().st_ino
    assert (first / "nested" / "stable.csv").stat().st_ino == (
        second / "nested" / "stable.csv"
    ).stat().st_ino
    assert (first / "answer.txt").stat().st_ino != (
        second / "answer.txt"
    ).stat().st_ino


def test_solution_snapshot_excludes_dependency_directories(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer\n")
    for name in (".venv", "venv", "packages"):
        dependency = workspace / name
        dependency.mkdir()
        (dependency / "large-library.so").write_bytes(b"library")

    snapshot = tmp_path / "snapshot"
    stats = copy_solution_workspace(workspace, snapshot)

    assert (snapshot / "answer.txt").is_file()
    assert stats.copied_files == 1
    assert all(not (snapshot / name).exists() for name in (".venv", "venv", "packages"))


def test_solution_snapshot_excludes_marker_identified_virtualenv(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    environment = workspace / "arbitrary-environment-name"
    environment.mkdir(parents=True)
    (workspace / "answer.txt").write_text("answer\n")
    (environment / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (environment / "bin").mkdir()
    (environment / "bin" / "python").symlink_to("/usr/bin/python")

    digest = solution_tree_sha256(workspace)
    snapshot = tmp_path / "snapshot"
    copy_solution_workspace(workspace, snapshot)

    assert len(digest) == 64
    assert not (snapshot / environment.name).exists()


def test_solution_snapshot_rejects_non_disposable_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("outside\n")
    (workspace / "answer.txt").symlink_to(target)

    with pytest.raises(RuntimeError, match="symlink"):
        copy_solution_workspace(workspace, tmp_path / "snapshot")


def test_historical_workspace_compaction_keeps_only_judge_inputs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "derived"
    nested.mkdir(parents=True)
    (workspace / "answer.txt").write_text("answer\n")
    (workspace / "trace.md").write_text("trace\n")
    (workspace / "analysis.py").write_text("print('work')\n")
    (nested / "large-result.bin").write_bytes(b"result" * 1024)
    make_tree_read_only(workspace)

    stats = compact_historical_workspace(workspace)

    assert sorted(path.name for path in workspace.iterdir()) == [
        "answer.txt",
        "trace.md",
    ]
    assert stats.removed_files == 2
    assert stats.removed_logical_bytes == len("print('work')\n") + len(
        b"result" * 1024
    )
    assert not workspace.stat().st_mode & stat.S_IWUSR
    repeated = compact_historical_workspace(workspace)
    assert repeated.removed_files == 0
    assert repeated.removed_logical_bytes == 0


def test_evaluation_run_hard_links_immutable_submission_inputs(
    tmp_path: Path,
) -> None:
    submission = tmp_path / "submission"
    workspace = submission / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    (workspace / "answer.txt").write_text("answer\n")
    (nested / "result.txt").write_text("result\n")
    (submission / "trajectory.stream.jsonl").write_text('{"turn": 0}\n')
    (submission / "status.json").write_text(json.dumps({
        "task": "da-1-1",
        "workspace_dir": str(workspace),
    }))

    run = prepare_evaluation_run(submission, tmp_path / "evaluation")

    assert (run / "workspace" / "answer.txt").stat().st_ino == (
        workspace / "answer.txt"
    ).stat().st_ino
    assert (run / "workspace" / "nested" / "result.txt").stat().st_ino == (
        nested / "result.txt"
    ).stat().st_ino
    assert (run / "trajectory.stream.jsonl").stat().st_ino == (
        submission / "trajectory.stream.jsonl"
    ).stat().st_ino
    assert json.loads((run / "status.json").read_text())["workspace_dir"] == str(
        run / "workspace"
    )
