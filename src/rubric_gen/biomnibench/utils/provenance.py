"""Fail-closed provenance for scientific experiment entry points."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.utils.hashing import sha256_file, sha256_text
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT


PROVENANCE_SCHEMA_VERSION = 1
_DEPENDENCIES = (
    "anthropic",
    "google-genai",
    "matplotlib",
    "openai",
    "pyarrow",
    "pytest",
    "tqdm",
)


def _git(*arguments: str) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(arguments)} failed: "
            + process.stderr.decode(errors="replace").strip()
        )
    return process.stdout


def repository_changes() -> tuple[str, ...]:
    raw = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    return tuple(
        entry.decode(errors="replace")
        for entry in raw.split(b"\0")
        if entry
    )


def require_clean_repository() -> None:
    changes = repository_changes()
    if changes:
        preview = "; ".join(changes[:8])
        suffix = "" if len(changes) <= 8 else f"; ... ({len(changes)} total)"
        raise RuntimeError(
            "scientific runs require a completely clean Git worktree: "
            + preview
            + suffix
        )


def tracked_tree_sha256() -> str:
    digest = hashlib.sha256()
    names = [name for name in _git("ls-files", "-z").split(b"\0") if name]
    for encoded in sorted(names):
        relative = encoded.decode("utf-8", errors="strict")
        path = PROJECT_ROOT / relative
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        if path.is_symlink():
            raw = os.readlink(path).encode()
            kind = b"symlink"
        elif path.is_file():
            raw = path.read_bytes()
            kind = b"file"
        else:
            raise RuntimeError(f"tracked source path is unavailable: {relative}")
        digest.update(len(kind).to_bytes(8, "big"))
        digest.update(kind)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def executable_provenance(executable: str) -> dict[str, object]:
    selected = shutil.which(executable)
    if selected is None:
        raise RuntimeError(f"required executable is unavailable: {executable}")
    path = Path(selected)
    resolved = path.resolve()
    process = subprocess.run(
        [str(path), "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=30,
        check=False,
    )
    if process.returncode != 0 or not process.stdout.strip():
        raise RuntimeError(f"could not attest executable version: {path}")
    return {
        "requested": executable,
        "path": str(path),
        "resolved_path": str(resolved),
        "sha256": sha256_file(resolved),
        "version_output": process.stdout.strip(),
    }


def source_provenance(*, require_clean: bool) -> dict[str, object]:
    changes = repository_changes()
    if require_clean and changes:
        require_clean_repository()
    commit = _git("rev-parse", "HEAD").decode().strip()
    lock = PROJECT_ROOT / "uv.lock"
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "git_commit": commit,
        "git_worktree_clean": not changes,
        "git_changes": list(changes),
        "tracked_tree_sha256": tracked_tree_sha256(),
        "uv_lock_sha256": sha256_file(lock) if lock.is_file() else None,
        "python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "packages": {
            name: _package_version(name)
            for name in _DEPENDENCIES
        },
    }


def agent_provenance(config: AgentRunConfig, *, require_clean: bool) -> dict[str, object]:
    executable = config.executable or config.provider
    value = {
        "source": source_provenance(require_clean=require_clean),
        "agent": {
            "provider": config.provider,
            "requested_model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "service_tier": config.service_tier,
            "retries": config.retries,
            "timeout_seconds": config.timeout_seconds,
            "isolation": "codex-custom-permission-profile",
            "command_network_access": False,
            "web_search": False,
            "executable": executable_provenance(executable),
        },
    }
    return {
        **value,
        "sha256": sha256_text(
            json.dumps(value, sort_keys=True, separators=(",", ":"))
        ),
    }


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None
