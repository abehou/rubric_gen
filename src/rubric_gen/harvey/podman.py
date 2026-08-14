"""Node-local rootless Podman configuration for Harvey LAB."""

from __future__ import annotations

import json
import os
import pwd
import shlex
import shutil
import stat
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path


def configured_podman_environment(
    source: Mapping[str, str] | None = None,
    *,
    temporary_root: Path | None = None,
    uid: int | None = None,
    username: str | None = None,
    subuid_path: Path = Path("/etc/subuid"),
    subgid_path: Path = Path("/etc/subgid"),
) -> dict[str, str]:
    """Return an environment suitable for rootless Podman on a Linux worker."""

    environment = dict(os.environ if source is None else source)
    if sys.platform != "linux":
        return environment

    resolved_uid = os.getuid() if uid is None else uid
    resolved_username = (
        pwd.getpwuid(resolved_uid).pw_name if username is None else username
    )
    local_root = temporary_root or _temporary_root(environment)
    podman_root = local_root / f"rubric-gen-podman-{resolved_uid}"
    configured_runtime = environment.get("XDG_RUNTIME_DIR")
    runtime = (
        Path(configured_runtime)
        if configured_runtime and _usable_runtime_directory(Path(configured_runtime))
        else podman_root / "runtime"
    )
    data = podman_root / "data"
    podman_home = podman_root / "home"
    config = podman_home / ".config"
    for path, label in (
        (runtime, "Podman runtime"),
        (data, "Podman data"),
        (podman_home, "Podman home"),
        (config, "Podman configuration"),
    ):
        _ensure_private_directory(path, label)
    environment.update(
        {
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_DATA_HOME": str(data),
            "XDG_CONFIG_HOME": str(config),
        }
    )
    policy = config / "containers" / "policy.json"
    _write_signature_policy(policy)
    _install_podman_wrapper(
        podman_root / "bin",
        environment=environment,
        home=podman_home,
        config=config,
        policy=policy,
    )

    identifiers = {resolved_username, str(resolved_uid)}
    has_subids = _has_subordinate_ids(subuid_path, identifiers) and (
        _has_subordinate_ids(subgid_path, identifiers)
    )
    if not has_subids and "CONTAINERS_STORAGE_CONF" not in environment:
        storage_config = config / "containers" / "storage.conf"
        _write_single_uid_storage_config(
            storage_config,
            runroot=podman_root / "storage-run",
            graphroot=data / "containers" / "storage",
        )
        environment["CONTAINERS_STORAGE_CONF"] = str(storage_config)
    return environment


def _temporary_root(environment: Mapping[str, str]) -> Path:
    configured = environment.get("SLURM_TMPDIR") or environment.get("TMPDIR")
    root = Path(configured) if configured else Path(tempfile.gettempdir())
    if not root.is_absolute():
        raise ValueError(f"Podman temporary root must be absolute: {root}")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _ensure_private_directory(path: Path, label: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{label} directory must be absolute: {path}")
    if path.is_symlink():
        raise ValueError(f"{label} directory must not be a symbolic link: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ValueError(f"{label} path is not a directory: {path}")
    path.chmod(stat.S_IRWXU)


def _usable_runtime_directory(path: Path) -> bool:
    try:
        details = path.lstat()
    except OSError:
        return False
    return (
        path.is_absolute()
        and stat.S_ISDIR(details.st_mode)
        and not stat.S_ISLNK(details.st_mode)
        and details.st_uid == os.getuid()
        and os.access(path, os.W_OK | os.X_OK)
    )


def _has_subordinate_ids(path: Path, identifiers: set[str]) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in lines:
        fields = line.strip().split(":")
        if len(fields) != 3 or fields[0] not in identifiers:
            continue
        try:
            if int(fields[2]) > 0:
                return True
        except ValueError:
            continue
    return False


def _write_single_uid_storage_config(
    path: Path,
    *,
    runroot: Path,
    graphroot: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = (
        "[storage]\n"
        'driver = "overlay"\n'
        f"runroot = {json.dumps(str(runroot))}\n"
        f"graphroot = {json.dumps(str(graphroot))}\n\n"
        "[storage.options.overlay]\n"
        'ignore_chown_errors = "true"\n'
        'mountopt = "nodev"\n'
    )
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Podman storage configuration is invalid: {path}")
        if path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_signature_policy(path: Path) -> None:
    content = json.dumps(
        {"default": [{"type": "insecureAcceptAnything"}]},
        indent=2,
        sort_keys=True,
    ) + "\n"
    _write_private_config(path, content, "Podman signature policy")


def _install_podman_wrapper(
    directory: Path,
    *,
    environment: dict[str, str],
    home: Path,
    config: Path,
    policy: Path,
) -> None:
    original_path = environment.get("PATH", os.defpath)
    resolved_directory = directory.resolve()
    search_entries = [
        entry
        for entry in original_path.split(os.pathsep)
        if Path(entry).resolve() != resolved_directory
    ]
    search_path = os.pathsep.join(search_entries)
    executable = shutil.which("podman", path=search_path)
    if executable is None:
        return

    _ensure_private_directory(directory, "Podman wrapper")
    wrapper = directory / "podman"
    content = (
        "#!/bin/sh\n"
        f"export HOME={shlex.quote(str(home))}\n"
        f"export XDG_CONFIG_HOME={shlex.quote(str(config))}\n"
        'case "${1:-}" in\n'
        "    build|pull)\n"
        '        command="$1"\n'
        "        shift\n"
        f"        exec {shlex.quote(executable)} \"$command\" "
        f"--signature-policy={shlex.quote(str(policy))} \"$@\"\n"
        "        ;;\n"
        "esac\n"
        f"exec {shlex.quote(executable)} \"$@\"\n"
    )
    _write_private_config(wrapper, content, "Podman wrapper")
    wrapper.chmod(stat.S_IRWXU)
    environment["PATH"] = f"{directory}{os.pathsep}{search_path}"


def _write_private_config(path: Path, content: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"{label} is invalid: {path}")
        if path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
