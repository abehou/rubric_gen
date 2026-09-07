"""Private per-run launcher; not part of rubric-gen's public CLI.

Usage: python bounded_run.py SECONDS COMMAND [ARGS...]
Writes no credentials. A deadline stops only the launched process tree.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time


def process_table():
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,lstart="],
        check=True, capture_output=True, text=True,
    )
    return {
        int(fields[0]): (int(fields[1]), " ".join(fields[2:]))
        for line in result.stdout.splitlines()
        if len(fields := line.split()) >= 7
    }


def signal_if_same(pid, identity, sig):
    if process_table().get(pid) != identity:
        return
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


def stop_owned_tree(process):
    table = process_table()
    if process.pid not in table:
        return
    owned = {process.pid: table[process.pid]}
    signal_if_same(process.pid, owned[process.pid], signal.SIGSTOP)
    # Freeze discovered children so they cannot continue spawning while the
    # controller is stopped. Re-read to catch children forked during discovery.
    while True:
        table = process_table()
        new = {pid: identity for pid, identity in table.items()
               if identity[0] in owned and pid not in owned}
        if not new:
            break
        owned.update(new)
        for pid, identity in new.items():
            signal_if_same(pid, identity, signal.SIGSTOP)
    for pid, identity in reversed(tuple(owned.items())):
        signal_if_same(pid, identity, signal.SIGTERM)
        signal_if_same(pid, identity, signal.SIGCONT)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    # PPIDs may change after their parent exits; the creation timestamp must
    # still match before a remaining owned process can be killed.
    current = process_table()
    for pid, (_parent, started) in owned.items():
        identity = current.get(pid)
        if identity is not None and identity[1] == started:
            signal_if_same(pid, identity, signal.SIGKILL)
    process.wait()


def main():
    seconds = float(sys.argv[1])
    command = sys.argv[2:]
    if seconds <= 0 or not command:
        raise ValueError("positive deadline and command required")
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    started = time.monotonic()
    process = subprocess.Popen(command, start_new_session=True)
    print(f"RUN_START pid={process.pid} limit_seconds={seconds:g}", flush=True)
    try:
        status = process.wait(timeout=max(0, seconds - (time.monotonic() - started)))
    except subprocess.TimeoutExpired:
        print("RUN_DEADLINE reached; stopping owned process tree", flush=True)
        stop_owned_tree(process)
        status = 124
    except KeyboardInterrupt:
        print("RUN_INTERRUPTED; stopping owned process tree", flush=True)
        stop_owned_tree(process)
        status = 130
    print(f"RUN_END status={status} elapsed_seconds={time.monotonic()-started:.1f}", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
