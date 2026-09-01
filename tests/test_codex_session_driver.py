from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.runtime.agents.codex_sessions as codex_sessions_module
from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import (
    CodexProviderHealthError,
    CodexSdkSessionDriver,
    is_codex_transport_error,
)
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.codex_rpc import CodexRpcGuard
from rubric_gen.submission_revision.study import (
    _ProviderCircuit,
    _ProviderCircuitOpen,
)


class TransportClosedError(RuntimeError):
    pass


class _Payload:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def model_dump(self, **_kwargs: object) -> dict[str, object]:
        return self.value


class _Handle:
    def __init__(
        self,
        turn_id: str,
        *,
        stream_error: Exception | None = None,
        close_event: threading.Event | None = None,
    ) -> None:
        self.id = turn_id
        self.stream_error = stream_error
        self.close_event = close_event
        self.interrupted = False

    def interrupt(self) -> None:
        self.interrupted = True

    def stream(self):
        if self.close_event is not None:
            self.close_event.wait()
            raise TransportClosedError("transport closed")
        yield SimpleNamespace(
            method="item/completed",
            payload=_Payload(
                {
                    "thread_id": "thread-1",
                    "turn_id": self.id,
                    "item": {
                        "id": f"item-{self.id}",
                        "type": "commandExecution",
                        "command": "write outputs",
                        "status": "completed",
                    },
                }
            ),
        )
        if self.stream_error is not None:
            raise self.stream_error
        yield SimpleNamespace(
            method="thread/tokenUsage/updated",
            payload=_Payload(
                {
                    "thread_id": "thread-1",
                    "turn_id": self.id,
                    "token_usage": {
                        "total": {
                            "input_tokens": 100,
                            "cached_input_tokens": 20,
                            "output_tokens": 10,
                            "reasoning_output_tokens": 2,
                            "total_tokens": 110,
                        }
                    },
                }
            ),
        )
        yield SimpleNamespace(
            method="turn/completed",
            payload=_Payload(
                {
                    "thread_id": "thread-1",
                    "turn": {"id": self.id, "status": "completed"},
                }
            ),
        )


class _Thread:
    id = "thread-1"

    def __init__(self, workspace, failures: list[Exception] | None = None) -> None:
        self.workspace = workspace
        self.failures = list(failures or [])
        self.prompts: list[str] = []
        self.stream_error: Exception | None = None
        self.block_stream = False
        self.close_event = threading.Event()

    def turn(self, prompt: str, **_kwargs: object) -> _Handle:
        self.prompts.append(prompt)
        if self.failures:
            raise self.failures.pop(0)
        (self.workspace / "trace.md").write_text("trace\n")
        (self.workspace / "answer.txt").write_text("answer\n")
        return _Handle(
            f"turn-{len(self.prompts)}",
            stream_error=self.stream_error,
            close_event=self.close_event if self.block_stream else None,
        )


class _Codex:
    def __init__(self, _config: object, thread: _Thread) -> None:
        self.thread = thread
        self.thread_start_calls = 0
        self.thread_resume_calls = 0
        self.closed = False

    def thread_start(self, **_kwargs: object) -> _Thread:
        self.thread_start_calls += 1
        return self.thread

    def thread_resume(self, _session_id: str, **_kwargs: object) -> _Thread:
        self.thread_resume_calls += 1
        return self.thread

    def close(self) -> None:
        self.closed = True
        self.thread.close_event.set()


class _Sdk:
    ApprovalMode = SimpleNamespace(deny_all="deny_all")

    def __init__(self, thread: _Thread) -> None:
        self.thread = thread
        self.clients: list[_Codex] = []
        self.configs: list[dict[str, object]] = []

    def CodexConfig(self, **kwargs: object) -> dict[str, object]:
        self.configs.append(kwargs)
        return kwargs

    def Codex(self, config: object) -> _Codex:
        client = _Codex(config, self.thread)
        self.clients.append(client)
        return client


def _driver(
    tmp_path,
    monkeypatch,
    thread: _Thread,
    *,
    retries: int = 2,
    timeout_seconds: int = 7_200,
):
    monkeypatch.setenv("CODEX_API_KEY", "test-key")
    monkeypatch.setattr(
        codex_sessions_module.shutil,
        "which",
        lambda _executable: sys.executable,
    )
    sdk = _Sdk(thread)
    delays: list[float] = []
    driver = CodexSdkSessionDriver(
        AgentRunConfig(
            provider="codex",
            model="gpt-5.6-luna",
            executable=sys.executable,
            retries=retries,
            timeout_seconds=timeout_seconds,
            quiet=True,
        ),
        contract=BIOMNIBENCH_DA,
        sdk_module=sdk,
        sleeper=delays.append,
    )
    return driver, sdk, delays


def test_codex_sdk_keeps_one_live_thread_across_turns(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    thread = _Thread(workspace)
    driver, sdk, _delays = _driver(tmp_path, monkeypatch, thread)
    reported: list[str] = []

    first = driver.start(
        workspace,
        "first prompt",
        tmp_path / "turn-1",
        on_session_id=reported.append,
    )
    second = driver.resume(
        workspace,
        "x" * 145_155,
        tmp_path / "turn-2",
        first.session_id,
    )

    assert first.exit_code == second.exit_code == 0
    assert reported == ["thread-1"]
    assert len(sdk.clients) == 1
    assert sdk.clients[0].thread_start_calls == 1
    assert sdk.clients[0].thread_resume_calls == 0
    assert thread.prompts == ["first prompt", "x" * 145_155]
    stream = (tmp_path / "turn-2" / "trajectory.stream.jsonl").read_text()
    assert '"type": "command_execution"' in stream
    status = json.loads((tmp_path / "turn-2" / "status.json").read_text())
    assert status["session_id"] == "thread-1"
    assert status["attempt_count"] == 1

    driver.close()
    assert sdk.clients[0].closed


def test_codex_sdk_retries_only_before_turn_start(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    thread = _Thread(
        workspace,
        [TransportClosedError("connection closed"), TransportClosedError("connection closed")],
    )
    driver, _sdk, delays = _driver(tmp_path, monkeypatch, thread)

    result = driver.start(workspace, "same prompt", tmp_path / "turn")

    assert result.exit_code == 0
    assert thread.prompts == ["same prompt"] * 3
    assert len(delays) == 2
    status = json.loads((tmp_path / "turn" / "status.json").read_text())
    assert len(status["attempts"][0]["pre_turn_failures"]) == 2
    assert status["attempt_count"] == 1


def test_codex_sdk_does_not_replay_prompt_after_stream_failure(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    thread = _Thread(workspace)
    thread.stream_error = TransportClosedError("response stream disconnected")
    driver, _sdk, _delays = _driver(tmp_path, monkeypatch, thread)

    with pytest.raises(CodexProviderHealthError, match="response stream disconnected"):
        driver.start(workspace, "one prompt", tmp_path / "turn")

    assert thread.prompts == ["one prompt"]
    status = json.loads((tmp_path / "turn" / "status.json").read_text())
    assert status["attempt_count"] == 1
    assert status["attempts"][0]["turn_started"] is True


def test_current_chatgpt_resume_failure_is_a_provider_health_error() -> None:
    error = RuntimeError(
        "WebSocket connection failed; thread/resume failed: "
        "list_turns is not supported yet"
    )
    assert is_codex_transport_error(error)


def test_invalid_json_rpc_is_a_provider_health_error() -> None:
    assert is_codex_transport_error(RuntimeError("Invalid JSON-RPC line: '\\n'"))


def test_real_sdk_defaults_to_its_bundled_cli() -> None:
    driver = CodexSdkSessionDriver(
        AgentRunConfig(provider="codex", model="gpt-5.6-luna"),
        contract=BIOMNIBENCH_DA,
    )

    executable = Path(driver.config.executable or "")

    assert executable.name == "codex"
    assert executable.parent.name == "bin"
    assert executable.is_file()


def test_codex_timeout_closes_transport_and_returns(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    thread = _Thread(workspace)
    thread.block_stream = True
    driver, sdk, _delays = _driver(
        tmp_path,
        monkeypatch,
        thread,
        retries=0,
        timeout_seconds=1,
    )

    started_at = time.monotonic()
    result = driver.start(workspace, "one prompt", tmp_path / "turn")

    assert time.monotonic() - started_at < 3
    assert result.exit_code == 124
    assert sdk.clients[0].closed
    stream = (tmp_path / "turn" / "trajectory.stream.jsonl").read_text()
    assert "Codex turn timed out" in stream


def test_rpc_guard_accepts_valid_notification_timestamp() -> None:
    guard = CodexRpcGuard()

    accepted, error = guard.server_message(
        json.dumps(
            {
                "method": "warning",
                "params": {"message": "safe"},
                "emittedAtMs": 1_777_777_777_777,
            }
        )
    )

    assert error is None
    assert accepted is not None


def test_rpc_guard_rejects_invalid_notification_timestamp() -> None:
    accepted, error = CodexRpcGuard().server_message(
        json.dumps(
            {
                "method": "warning",
                "params": {"message": "unsafe"},
                "emittedAtMs": "now",
            }
        )
    )

    assert accepted is None
    assert error == "ValueError: emittedAtMs must be a non-negative integer"


def test_app_server_proxy_isolates_non_rpc_output(tmp_path) -> None:
    fake_codex = tmp_path / "fake-codex"
    fake_codex.write_text(
        f"""#!{sys.executable}
import json
import sys
from websockets.sync.server import unix_serve

listen = sys.argv[sys.argv.index("--listen") + 1]
path = listen.removeprefix("unix://")

def handle(connection):
    request = json.loads(connection.recv())
    connection.send("")
    connection.send("data/idr_ranges.xlsx is ordinary command output")
    connection.send(json.dumps({{"id": "wrong-request", "result": {{}}}}))
    connection.send(json.dumps({{"method": "unknown/output", "params": {{}}}}))
    connection.send(json.dumps({{"method": "turn/completed", "params": {{}}}}))
    connection.send(json.dumps({{
        "method": "warning",
        "params": {{"message": "safe"}},
        "emittedAtMs": 1777777777777,
    }}))
    response = {{
        "id": request["id"],
        "result": {{
            "serverInfo": {{"name": "fake"}},
            "largePayload": "x" * 1_100_000,
        }},
    }}
    connection.send(json.dumps(response))
    connection.close()
    server.shutdown()

server = unix_serve(handle, path)
print("", flush=True)
print("data/idr_ranges.xlsx is ordinary command output", flush=True)
server.serve_forever()
"""
    )
    fake_codex.chmod(0o755)
    workspace = tmp_path / "workspace"
    state_home = tmp_path / "home"
    temporary = tmp_path / "tmp"
    codex_home = tmp_path / "codex-home"
    for path in (workspace, state_home, temporary, codex_home):
        path.mkdir()
    request = {"id": "request-1", "method": "initialize", "params": {}}

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "rubric_gen.runtime.agents.codex_app_server",
            str(fake_codex),
            str(workspace),
            str(state_home),
            str(temporary),
            str(codex_home),
        ],
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    readable, _, _ = select.select([process.stdout], [], [], 5)
    if not readable:
        process.terminate()
        process.wait(timeout=5)
        pytest.fail(f"proxy did not return JSON-RPC: {process.stderr.read()}")
    first_response = process.stdout.readline()
    second_response = process.stdout.readline()
    process.wait(timeout=5)
    responses = [first_response, second_response, *process.stdout.readlines()]
    stderr = process.stderr.read()

    assert process.returncode == 0, stderr
    assert [json.loads(line) for line in responses] == [{
        "method": "warning",
        "params": {"message": "safe"},
        "emittedAtMs": 1777777777777,
    }, {
        "id": "request-1",
        "result": {
            "serverInfo": {"name": "fake"},
            "largePayload": "x" * 1_100_000,
        },
    }]
    assert "data/idr_ranges.xlsx is ordinary command output" in stderr
    assert stderr.count("discarded invalid JSON-RPC frame") == 5


def test_provider_circuit_opens_after_three_transport_failures() -> None:
    circuit = _ProviderCircuit("codex")
    for index in range(3):
        circuit.check()
        circuit.record_failure(CodexProviderHealthError(f"failure {index}"))
    circuit.record_success()

    with pytest.raises(_ProviderCircuitOpen, match="3 transport failures"):
        circuit.check()
