"""Proxy Codex app-server over a private Unix socket."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, unix_connect

from rubric_gen.runtime.agents.adapters import sanitized_agent_environment
from rubric_gen.runtime.agents.codex_rpc import CodexRpcGuard


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit(
            "usage: codex_app_server EXECUTABLE WORKSPACE HOME TMPDIR CODEX_HOME"
        )
    executable, workspace, state_home, temporary, codex_home = sys.argv[1:]
    environment = sanitized_agent_environment()
    environment.update(
        {
            "HOME": state_home,
            "TMPDIR": temporary,
            "CODEX_HOME": codex_home,
            "PWD": workspace,
            "NO_COLOR": "1",
        }
    )
    for key in ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        if key in os.environ:
            environment[key] = os.environ[key]
    resolved = str(Path(executable).resolve(strict=True))
    if os.name != "posix":
        raise RuntimeError("Codex scientific sessions require a POSIX host")
    socket_path = Path(f"/tmp/rg-codex-{os.getuid()}-{secrets.token_hex(8)}.sock")
    arguments = [
        resolved,
        "app-server",
        "--strict-config",
        "--listen",
        f"unix://{socket_path}",
    ]
    process = subprocess.Popen(
        arguments,
        cwd=workspace,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )

    def terminate_on_signal(_signum: int, _frame: object) -> None:
        _terminate(process)
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, terminate_on_signal)
    signal.signal(signal.SIGINT, terminate_on_signal)
    connection: ClientConnection | None = None
    try:
        connection = _connect(process, socket_path)
        guard = CodexRpcGuard()
        request_thread = threading.Thread(
            target=_forward_requests,
            args=(connection, guard),
            daemon=True,
        )
        request_thread.start()
        _forward_responses(connection, guard)
        return process.poll() or 0
    finally:
        if connection is not None:
            connection.close()
        _terminate(process)
        socket_path.unlink(missing_ok=True)


def _connect(process: subprocess.Popen[bytes], path: Path) -> ClientConnection:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Codex app-server exited before accepting RPC: {exit_code}"
            )
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            time.sleep(0.02)
            continue
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("Codex app-server created an unsafe RPC socket")
        try:
            return unix_connect(
                str(path),
                uri="ws://localhost",
                compression=None,
                open_timeout=2,
                close_timeout=2,
                max_size=None,
            )
        except ConnectionRefusedError:
            time.sleep(0.02)
    raise TimeoutError("Codex app-server did not create its RPC socket")


def _forward_requests(
    connection: ClientConnection,
    guard: CodexRpcGuard,
) -> None:
    pending = b""
    try:
        while chunk := os.read(sys.stdin.fileno(), 65_536):
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                raw = line.removesuffix(b"\r").decode("utf-8")
                connection.send(guard.client_message(raw))
        if pending:
            connection.send(guard.client_message(pending.decode("utf-8")))
    except (BrokenPipeError, ConnectionClosed, ConnectionError, OSError):
        pass
    except (UnicodeError, ValueError) as exc:
        print(f"Codex SDK emitted invalid JSON-RPC: {exc}", file=sys.stderr)
        connection.close(code=1002, reason="invalid client JSON-RPC")


def _forward_responses(
    connection: ClientConnection,
    guard: CodexRpcGuard,
) -> None:
    for message in connection:
        if isinstance(message, bytes):
            try:
                message = message.decode("utf-8")
            except UnicodeError as exc:
                _report_discard(repr(message), f"{type(exc).__name__}: {exc}")
                continue
        validated, error = guard.server_message(message)
        if validated is None:
            _report_discard(message, error or "unknown validation error")
            continue
        sys.stdout.write(validated + "\n")
        sys.stdout.flush()


def _report_discard(raw: str, reason: str) -> None:
    encoded = raw.encode("utf-8", errors="replace")
    digest = hashlib.sha256(encoded).hexdigest()
    preview = json.dumps(raw[:160], ensure_ascii=True)
    print(
        "Codex app-server discarded invalid JSON-RPC frame: "
        f"{reason}; bytes={len(encoded)}; sha256={digest}; preview={preview}",
        file=sys.stderr,
        flush=True,
    )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
