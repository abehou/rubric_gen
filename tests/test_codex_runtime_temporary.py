from pathlib import Path
import tomllib

import pytest

from rubric_gen.runtime.agents.codex_app_server import (
    _local_cli_cache,
    _local_cli_temporary,
    _runtime_filesystem_override,
)


def test_runtime_permissions_preserve_controlled_mounts_and_dotted_paths(tmp_path: Path):
    home = tmp_path / ".agent-state" / "codex"
    home.mkdir(parents=True)
    config = '[permissions.benchmark-task.filesystem]\n":minimal"="read"\n"/runtime/python.3.12"="read"\n[permissions.benchmark-task.filesystem.":workspace_roots"]\n"."="write"\n'
    (home / "config.toml").write_text(config)
    runtime = tmp_path / "local"
    override = _runtime_filesystem_override(home, runtime)
    actual = tomllib.loads('filesystem=' + override.split('=', 1)[1])['filesystem']
    original = tomllib.loads(config)['permissions']['benchmark-task']['filesystem']
    assert actual == {**original, str(runtime): 'read', str(home / 'tmp'): 'read'}
    assert str(home) not in actual


@pytest.mark.parametrize("fail", [False, True])
def test_temporary_relocation_preserves_existing_state(tmp_path: Path, fail: bool):
    home = tmp_path / "home"
    (home / "tmp").mkdir(parents=True)
    (home / "tmp" / "old-lock").write_bytes(b"original temporary evidence")
    (home / "sessions").mkdir()
    (home / "sessions" / "session.jsonl").write_bytes(b"persistent session")
    runtime = tmp_path / "local-runtime"
    try:
        with _local_cli_temporary(home, runtime):
            assert (home / "tmp").is_symlink()
            assert (home / "tmp").resolve() == runtime / "cli-tmp"
            (home / "tmp" / "new-lock").write_bytes(b"local only")
            assert (runtime / "cli-tmp" / "new-lock").is_file()
            if fail:
                raise ValueError("synthetic startup failure")
    except ValueError:
        assert fail
    assert not (home / "tmp").is_symlink()
    assert (home / "tmp" / "old-lock").read_bytes() == b"original temporary evidence"
    assert not (home / "tmp" / "new-lock").exists()
    assert (home / "sessions" / "session.jsonl").read_bytes() == b"persistent session"
    assert not list(home.glob(".tmp-preserved-*"))


def test_fresh_home_does_not_leave_a_dangling_runtime_link(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    with _local_cli_temporary(home, tmp_path / "local"):
        assert (home / "tmp").is_symlink()
    assert not (home / "tmp").exists()
    assert not (home / "tmp").is_symlink()


def test_existing_runtime_link_requires_owner_reconciliation(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "tmp").symlink_to(tmp_path / "missing-node-runtime")
    with pytest.raises(RuntimeError, match="terminal-owner reconciliation"):
        with _local_cli_temporary(home, tmp_path / "local"):
            pytest.fail("must not reuse another owner's runtime link")
    assert (home / "tmp").readlink() == tmp_path / "missing-node-runtime"


def test_dead_owned_runtime_link_is_reconciled_before_reuse(tmp_path: Path):
    home = tmp_path / "home"
    home.mkdir()
    backup = home / ".tmp-preserved-interrupted"
    backup.mkdir()
    (backup / "evidence").write_text("preserved")
    stale = Path(f"/tmp/rg-codex-{__import__('os').getuid()}-dead/runtime/cli-tmp")
    (home / "tmp").symlink_to(stale, target_is_directory=True)

    with _local_cli_temporary(home, tmp_path / "new-runtime"):
        assert (home / "tmp").resolve() == tmp_path / "new-runtime/cli-tmp"

    assert not (home / "tmp").is_symlink()
    assert (home / "tmp/evidence").read_text() == "preserved"
    assert not list(home.glob(".tmp-preserved-*"))


@pytest.mark.parametrize("fail", [False, True])
def test_local_cache_preserves_persistent_state(tmp_path: Path, fail: bool):
    home = tmp_path / "home"
    cache = home / "cache"
    cache.mkdir(parents=True)
    (cache / "catalog").write_text("persistent")
    runtime = tmp_path / "runtime"
    try:
        with _local_cli_cache(home, runtime):
            assert cache.is_symlink()
            assert cache.resolve() == runtime / "cli-cache"
            (cache / "ephemeral").write_text("local")
            if fail:
                raise ValueError("synthetic app-server failure")
    except ValueError:
        assert fail

    assert not cache.is_symlink()
    assert (cache / "catalog").read_text() == "persistent"
    assert not (cache / "ephemeral").exists()
    assert not list(home.glob(".cache-preserved-*"))
