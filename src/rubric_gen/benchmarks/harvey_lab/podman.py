"""Rootless Podman runtime with a portable shared Harvey image cache."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path


def configured_podman_environment(
    source: Mapping[str, str] | None = None,
    *,
    cache_root: Path,
    temporary_root: Path | None = None,
    uid: int | None = None,
    username: str | None = None,
    subuid_path: Path = Path("/etc/subuid"),
    subgid_path: Path = Path("/etc/subgid"),
    cgroup_limits_available: bool | None = None,
) -> dict[str, str]:
    """Return an environment with local Podman state and shared reusable caches."""

    environment = dict(os.environ if source is None else source)
    resolved_uid = os.getuid() if uid is None else uid
    shared = _shared_user_cache(cache_root, resolved_uid)
    uv_cache = shared / "uv"
    _ensure_private_directory(uv_cache, "Harvey UV cache")
    environment["UV_CACHE_DIR"] = str(uv_cache)
    if sys.platform != "linux":
        return environment

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
        cgroup_limits_available=(
            _cgroup_limits_available()
            if cgroup_limits_available is None
            else cgroup_limits_available
        ),
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


def restore_cached_image(
    environment: Mapping[str, str],
    *,
    cache_root: Path,
    image: str,
    uid: int | None = None,
) -> bool:
    """Load a shared OCI image archive when the image is absent locally."""

    if _inspect_image_id(environment, image) is not None:
        return True
    shared = _shared_user_cache(cache_root, os.getuid() if uid is None else uid)
    reference = _image_reference_path(shared, image)
    if not reference.exists():
        return False
    metadata = _read_image_reference(reference, image)
    expected_id = str(metadata["image_id"])
    archive = _image_blob_path(shared, expected_id)
    if archive.is_symlink() or not archive.is_file():
        raise RuntimeError(f"Harvey image cache archive is missing: {archive}")
    result = subprocess.run(
        ["podman", "load", "--input", str(archive)],
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"could not load Harvey image cache {archive}: {detail}")
    observed_id = _inspect_image_id(environment, image)
    if observed_id != expected_id:
        raise RuntimeError(
            f"Harvey image cache restored {observed_id!r}; expected {expected_id!r}"
        )
    return True


def cache_image(
    environment: Mapping[str, str],
    *,
    cache_root: Path,
    image: str,
    uid: int | None = None,
) -> Path:
    """Save a local Podman image as an immutable shared OCI archive."""

    image_id = _inspect_image_id(environment, image)
    if image_id is None:
        raise RuntimeError(f"cannot cache missing Podman image: {image}")
    shared = _shared_user_cache(cache_root, os.getuid() if uid is None else uid)
    blobs = shared / "images" / "blobs"
    references = shared / "images" / "refs"
    _ensure_private_directory(blobs, "Harvey image blob cache")
    _ensure_private_directory(references, "Harvey image reference cache")
    archive = _image_blob_path(shared, image_id)
    if archive.exists():
        if archive.is_symlink() or not archive.is_file():
            raise RuntimeError(f"Harvey image cache archive is invalid: {archive}")
    else:
        temporary = archive.with_name(
            f".{archive.name}.tmp-{secrets.token_hex(8)}"
        )
        if temporary.exists():
            raise RuntimeError(f"Harvey image cache temporary path exists: {temporary}")
        result = subprocess.run(
            [
                "podman", "save", "--format", "oci-archive",
                "--output", str(temporary), image,
            ],
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if result.returncode != 0:
            if temporary.exists() and temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"could not cache Harvey image {image}: {detail}")
        if temporary.is_symlink() or not temporary.is_file():
            raise RuntimeError(f"Podman did not create the image archive: {temporary}")
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, archive)
    _write_atomic_json(
        _image_reference_path(shared, image),
        {"image": image, "image_id": image_id},
    )
    return archive


def _shared_user_cache(cache_root: Path, uid: int) -> Path:
    root = cache_root.expanduser()
    if not root.is_absolute():
        raise ValueError(f"Harvey cache root must be absolute: {root}")
    if root.is_symlink():
        raise ValueError(f"Harvey cache root must not be a symbolic link: {root}")
    shared = root.resolve() / f"user-{uid}"
    _ensure_private_directory(shared, "Harvey shared cache")
    return shared


def _image_reference_path(shared: Path, image: str) -> Path:
    key = hashlib.sha256(image.encode("utf-8")).hexdigest()
    return shared / "images" / "refs" / f"{key}.json"


def _image_blob_path(shared: Path, image_id: str) -> Path:
    key = hashlib.sha256(image_id.encode("utf-8")).hexdigest()
    return shared / "images" / "blobs" / f"{key}.oci.tar"


def _inspect_image_id(environment: Mapping[str, str], image: str) -> str | None:
    result = subprocess.run(
        ["podman", "image", "inspect", "--format", "{{.Id}}", image],
        env=dict(environment),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    image_id = result.stdout.strip()
    if not image_id:
        raise RuntimeError(f"Podman returned an empty image ID for {image}")
    return image_id


def _read_image_reference(path: Path, image: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Harvey image cache reference is invalid: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Harvey image cache reference is invalid: {path}") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"image", "image_id"}
        or value.get("image") != image
        or type(value.get("image_id")) is not str
        or not value["image_id"]
    ):
        raise RuntimeError(f"Harvey image cache reference is invalid: {path}")
    return value


def _write_atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp-{secrets.token_hex(8)}")
    if temporary.exists():
        raise RuntimeError(f"Harvey image reference temporary path exists: {temporary}")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    os.replace(temporary, path)


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
    cgroup_limits_available: bool,
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
    run_case = ""
    if not cgroup_limits_available:
        run_case = (
            "    run)\n"
            "        filtered=()\n"
            "        for argument in \"$@\"; do\n"
            "            case \"$argument\" in\n"
            "                --cpus=*|--memory=*|--pids-limit=*) ;;\n"
            "                *) filtered+=(\"$argument\") ;;\n"
            "            esac\n"
            "        done\n"
            f"        exec {shlex.quote(executable)} \"${{filtered[@]}}\"\n"
            "        ;;\n"
        )
    content = (
        "#!/bin/bash\n"
        f"export HOME={shlex.quote(str(home))}\n"
        f"export XDG_CONFIG_HOME={shlex.quote(str(config))}\n"
        'case "${1:-}" in\n'
        "    pull)\n"
        '        command="$1"\n'
        "        shift\n"
        '        image=""\n'
        '        for argument in "$@"; do image="$argument"; done\n'
        f'        if [ -n "$image" ] && {shlex.quote(executable)} image exists "$image"; then\n'
        "            exit 0\n"
        "        fi\n"
        f"        exec {shlex.quote(executable)} \"$command\" "
        f"--signature-policy={shlex.quote(str(policy))} \"$@\"\n"
        "        ;;\n"
        "    build)\n"
        '        command="$1"\n'
        "        shift\n"
        f"        exec {shlex.quote(executable)} \"$command\" "
        f"--signature-policy={shlex.quote(str(policy))} \"$@\"\n"
        "        ;;\n"
        f"{run_case}"
        "esac\n"
        f"exec {shlex.quote(executable)} \"$@\"\n"
    )
    _write_private_config(wrapper, content, "Podman wrapper")
    wrapper.chmod(stat.S_IRWXU)
    environment["PATH"] = f"{directory}{os.pathsep}{search_path}"


def _cgroup_limits_available() -> bool:
    """Return false for a Slurm cgroup that does not permit child cgroups."""

    if sys.platform != "linux":
        return True
    try:
        value = Path("/proc/self/cgroup").read_text(encoding="utf-8").strip()
        if not value.startswith("0::"):
            return True
        relative = value.split("::", 1)[1]
        cgroup = Path("/sys/fs/cgroup") / relative.lstrip("/")
        return "slurmstepd.scope" not in cgroup.parts or os.access(cgroup, os.W_OK)
    except OSError:
        return True


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
