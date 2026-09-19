"""POSIX subprocess-tree cleanup across nested process groups."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path


def _process_table() -> list[tuple[int, int, int]]:
    """Return ``(pid, parent_pid, process_group_id)`` rows from POSIX ``ps``."""

    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pgid="],
        check=False,
        capture_output=True,
        text=True,
    )
    rows: list[tuple[int, int, int]] = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            rows.append(tuple(int(field) for field in fields))
        except ValueError:
            continue
    return rows


def _child_pids(parent_pid: int) -> tuple[int, ...]:
    if sys.platform == "darwin":
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        libproc.proc_listchildpids.argtypes = [
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        libproc.proc_listchildpids.restype = ctypes.c_int
        capacity = libproc.proc_listchildpids(parent_pid, None, 0)
        if capacity <= 0:
            return ()
        buffer = (ctypes.c_int * capacity)()
        count = libproc.proc_listchildpids(
            parent_pid,
            buffer,
            ctypes.sizeof(buffer),
        )
        if count <= 0:
            return ()
        return tuple(pid for pid in buffer[:count] if pid > 0)

    children_path = Path(f"/proc/{parent_pid}/task/{parent_pid}/children")
    if children_path.is_file():
        try:
            return tuple(int(pid) for pid in children_path.read_text().split())
        except (OSError, ValueError):
            return ()

    return tuple(
        pid
        for pid, candidate_parent, _ in _process_table()
        if candidate_parent == parent_pid
    )


def _descendant_pids(root_pid: int) -> set[int]:
    descendants: set[int] = set()
    pending = [root_pid]
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(_child_pids(pid))
    return descendants


def descendant_process_groups(
    root_pid: int,
    rows: list[tuple[int, int, int]] | None = None,
) -> tuple[int, ...]:
    """Find every process group currently rooted below ``root_pid``.

    Agent sandboxes may create their own sessions.  Killing only the direct
    child's process group therefore leaves those nested groups orphaned.
    """

    groups: dict[int, int] = {}
    if rows is None:
        descendants = _descendant_pids(root_pid)
        for pid in descendants:
            try:
                groups[pid] = os.getpgid(pid)
            except ProcessLookupError:
                continue
    else:
        children: dict[int, list[int]] = defaultdict(list)
        for pid, parent_pid, process_group_id in rows:
            children[parent_pid].append(pid)
            groups[pid] = process_group_id
        descendants = set()
        pending = [root_pid]
        while pending:
            pid = pending.pop()
            if pid in descendants:
                continue
            descendants.add(pid)
            pending.extend(children.get(pid, ()))

    current_group = os.getpgrp()
    process_groups = {
        groups.get(pid, pid)
        for pid in descendants
        if groups.get(pid, pid) > 0 and groups.get(pid, pid) != current_group
    }
    return tuple(sorted(process_groups, reverse=True))


def terminate_posix_process_tree(root_pid: int, *, grace_seconds: float = 0.1) -> None:
    """Terminate all currently visible descendant groups of ``root_pid``."""

    if os.name != "posix":  # pragma: no cover - POSIX experiment runtime only.
        return
    process_groups = set(descendant_process_groups(root_pid))
    for process_group_id in process_groups:
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except OSError:
            pass
    if grace_seconds:
        time.sleep(grace_seconds)

    # Include groups created during graceful shutdown while the root is visible.
    process_groups.update(descendant_process_groups(root_pid))
    for process_group_id in process_groups:
        try:
            os.killpg(process_group_id, signal.SIGKILL)
        except OSError:
            pass
