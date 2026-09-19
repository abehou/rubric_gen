"""OS-enforced resource limits for benchmark coding-agent processes."""

from __future__ import annotations

import os
import resource
import sys
from collections.abc import Sequence
from pathlib import Path


MAX_AGENT_OUTPUT_FILE_BYTES = 512 * 1024 * 1024


def limited_agent_command(
    command: Sequence[str],
    *,
    max_file_bytes: int = MAX_AGENT_OUTPUT_FILE_BYTES,
) -> list[str]:
    """Run an agent command beneath an inherited regular-file size ceiling."""

    if os.name != "posix":  # pragma: no cover - scientific runs require POSIX.
        raise RuntimeError("agent file-size limits require a POSIX host")
    if not command:
        raise ValueError("agent command must not be empty")
    if type(max_file_bytes) is not int or max_file_bytes < 1:
        raise ValueError("agent file-size limit must be a positive integer")
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        str(max_file_bytes),
        *command,
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Apply the hard limit and replace this process with the agent command."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 2:
        raise SystemExit("usage: resource_limits MAX_FILE_BYTES COMMAND [ARG ...]")
    try:
        max_file_bytes = int(arguments[0])
    except ValueError as exc:
        raise SystemExit("MAX_FILE_BYTES must be a positive integer") from exc
    if max_file_bytes < 1:
        raise SystemExit("MAX_FILE_BYTES must be a positive integer")
    command = arguments[1:]
    resource.setrlimit(
        resource.RLIMIT_FSIZE,
        (max_file_bytes, max_file_bytes),
    )
    os.execvpe(command[0], command, os.environ)
    raise AssertionError("os.execvpe returned unexpectedly")


if __name__ == "__main__":  # pragma: no cover - exercised through subprocesses.
    raise SystemExit(main())
