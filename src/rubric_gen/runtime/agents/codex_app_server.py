"""Proxy Codex app-server over a private Unix socket."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, unix_connect

from rubric_gen.runtime.agents.adapters import sanitized_agent_environment
from rubric_gen.runtime.agents.codex_rpc import CodexRpcGuard
from rubric_gen.runtime.agents.codex_completion import TurnCompletionBuffer


def main() -> int:
    if len(sys.argv) != 6:
        raise SystemExit(
            "usage: codex_app_server EXECUTABLE WORKSPACE HOME TMPDIR CODEX_HOME"
        )
    executable, workspace, state_home, temporary, codex_home = sys.argv[1:]
    environment = sanitized_agent_environment()
    # SDK launch reconstructs the environment here instead of forwarding the
    # adapter's dictionary. Preserve the same project interpreter on this path.
    python_bin = str((Path(sys.prefix) / "bin").resolve())
    environment["PATH"] = os.pathsep.join(
        (python_bin, environment.get("PATH", ""))
    ).rstrip(os.pathsep)
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
    # Codex rejects a symlink as the immediate parent of its listening socket.
    # On macOS, `/tmp` is a symlink, so create a private real directory below it.
    with tempfile.TemporaryDirectory(
        prefix=f"rg-codex-{os.getuid()}-{secrets.token_hex(4)}-", dir="/tmp"
    ) as socket_root:
        socket_dir = Path(socket_root)
        with _local_cli_temporary(Path(codex_home), socket_dir / "runtime"):
            socket_path = socket_dir / "rpc.sock"
            runtime = socket_dir / "runtime"
            environment["TMPDIR"] = str(runtime)
            helper_bin = runtime / "bin"
            helper_bin.mkdir()
            (helper_bin / "codex-linux-sandbox").symlink_to(resolved)
            first, _, remainder = environment["PATH"].partition(os.pathsep)
            environment["PATH"] = os.pathsep.join((first, str(helper_bin), remainder))
            arguments = [
                resolved,
                "app-server",
                "--strict-config",
                "-c",
                _runtime_filesystem_override(Path(codex_home), runtime),
                "-c",
                f"shell_environment_policy.set.TMPDIR={json.dumps(temporary)}",
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
                # Finish cleanup before the SDK force-kills this wrapper after
                # two seconds; do not wait for a WebSocket close handshake first.
                _terminate(process)
                if connection is not None:
                    connection.close()
                socket_path.unlink(missing_ok=True)


@contextmanager
def _local_cli_temporary(codex_home: Path, runtime: Path):
    """Relocate disposable CLI locks while preserving persistent session state.

    The caller must exclusively own this Codex home, as for the app-server
    itself. Existing temporary contents are restored without modification.
    A hard kill may leave the link and backup: fail closed on the next start
    until the terminal owner's runtime link is reconciled, never guess ownership.
    """
    runtime.mkdir(mode=0o700)
    cli_tmp = runtime / "cli-tmp"
    cli_tmp.mkdir(mode=0o700)
    original = codex_home / "tmp"
    backup = None
    if os.path.lexists(original):
        if original.is_symlink() or not original.is_dir():
            raise RuntimeError("Codex tmp requires terminal-owner reconciliation: " + str(original))
        backup = codex_home / (".tmp-preserved-" + secrets.token_hex(12))
        original.rename(backup)
    linked = False
    try:
        original.symlink_to(cli_tmp, target_is_directory=True)
        linked = True
        yield
    finally:
        if linked:
            if not original.is_symlink() or original.readlink() != cli_tmp:
                raise RuntimeError("Codex runtime temporary link changed during owned session")
            original.unlink()
        if backup is not None:
            if os.path.lexists(original):
                raise RuntimeError("Codex temporary backup preserved; destination occupied")
            backup.rename(original)


def _runtime_filesystem_override(codex_home: Path, runtime: Path) -> str:
    # Override the complete controlled filesystem table: CLI dotted keys do not
    # parse quoted path segments, and persistent home paths can contain dots.
    config = tomllib.loads((codex_home / "config.toml").read_text())
    filesystem = dict(config["permissions"]["benchmark-task"]["filesystem"])
    filesystem[str(runtime)] = "read"
    # App-server uses this absolute helper alias, not only PATH lookup.
    filesystem[str(codex_home / "tmp")] = "read"

    def table(value: dict) -> str:
        fields = []
        for key, item in value.items():
            if isinstance(item, dict):
                encoded = table(item)
            elif isinstance(item, str):
                encoded = json.dumps(item)
            else:
                raise RuntimeError("Unexpected controlled Codex filesystem value")
            fields.append(json.dumps(key) + "=" + encoded)
        return "{" + ",".join(fields) + "}"

    return "permissions.benchmark-task.filesystem=" + table(filesystem)


def _connect(process: subprocess.Popen[bytes], path: Path) -> ClientConnection:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise RuntimeError(
                f"Codex app-server exited before accepting RPC: {exit_code}"
            )
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            time.sleep(0.1)
            continue
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise RuntimeError("Codex app-server created an unsafe RPC socket")
        try:
            return unix_connect(
                str(path),
                uri="ws://localhost",
                compression=None,
                open_timeout=2,
                close_timeout=0.25,
                max_size=None,
            )
        except ConnectionRefusedError:
            time.sleep(0.1)
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
        connection.close()
    except (BrokenPipeError, ConnectionClosed, ConnectionError, OSError):
        pass
    except (UnicodeError, ValueError) as exc:
        print(f"Codex SDK emitted invalid JSON-RPC: {exc}", file=sys.stderr)
        connection.close(code=1002, reason="invalid client JSON-RPC")


def _forward_responses(
    connection: ClientConnection,
    guard: CodexRpcGuard,
) -> None:
    completion = TurnCompletionBuffer()
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
        for ready in completion.accept(validated):
            sys.stdout.write(ready + "\n")
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
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.5)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
