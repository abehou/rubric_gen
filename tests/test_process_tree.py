from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rubric_gen.runtime.process_tree import (
    descendant_process_groups,
    terminate_posix_process_tree,
)


def test_descendant_process_groups_crosses_nested_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "getpgrp", lambda: 999)
    rows = [
        (10, 1, 10),
        (11, 10, 10),
        (12, 11, 12),
        (13, 12, 13),
        (20, 1, 20),
    ]

    assert descendant_process_groups(10, rows) == (13, 12, 10)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_terminate_posix_process_tree_kills_nested_session(tmp_path: Path) -> None:
    script = tmp_path / "parent.py"
    script.write_text(
        "\n".join(
            (
                "import signal, subprocess, sys, time",
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'], "
                "start_new_session=True)",
                "print(child.pid, flush=True)",
                "time.sleep(60)",
            )
        )
    )
    parent = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert parent.stdout is not None
    nested_pid = int(parent.stdout.readline())
    try:
        terminate_posix_process_tree(parent.pid)
        parent.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.getpgid(nested_pid)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("nested process group survived tree termination")
    finally:
        for process_group_id in (nested_pid, parent.pid):
            try:
                os.killpg(process_group_id, 9)
            except ProcessLookupError:
                pass
