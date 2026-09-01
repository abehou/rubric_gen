"""Strict JSON-RPC boundary for the Codex app-server proxy."""

from __future__ import annotations

import json
import threading
from typing import TypeAlias

from openai_codex.generated.notification_registry import NOTIFICATION_MODELS


RpcId: TypeAlias = str | int
_SERVER_REQUEST_METHODS = frozenset(
    {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }
)
_SERVER_NOTIFICATION_METADATA = frozenset({"emittedAtMs"})


class CodexRpcGuard:
    """Allow only correlated messages from the current Codex SDK protocol."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._client_requests: set[RpcId] = set()
        self._server_requests: set[RpcId] = set()

    def client_message(self, raw: str) -> str:
        """Validate one trusted SDK message and record its request identity."""
        message = _object(raw)
        with self._lock:
            if "method" in message:
                _validate_method_message(message)
                if "id" in message:
                    request_id = _message_id(message)
                    if request_id in self._client_requests:
                        raise ValueError("duplicate client request id")
                    self._client_requests.add(request_id)
            else:
                request_id = _validate_response(message)
                if request_id not in self._server_requests:
                    raise ValueError("client response has no pending server request")
                self._server_requests.remove(request_id)
        return _canonical(message)

    def server_message(self, raw: str) -> tuple[str | None, str | None]:
        """Return a validated server message or its rejection reason."""
        try:
            message = _object(raw)
            with self._lock:
                if "method" in message:
                    _validate_method_message(
                        message,
                        allowed_metadata=(
                            _SERVER_NOTIFICATION_METADATA
                            if "id" not in message
                            else frozenset()
                        ),
                    )
                    method = message["method"]
                    if "id" in message:
                        if method not in _SERVER_REQUEST_METHODS:
                            raise ValueError("unknown server request method")
                        request_id = _message_id(message)
                        if request_id in self._server_requests:
                            raise ValueError("duplicate server request id")
                        self._server_requests.add(request_id)
                    else:
                        model = NOTIFICATION_MODELS.get(method)
                        if model is None:
                            raise ValueError("unknown server notification method")
                        params = message.get("params", {})
                        model.model_validate(params if params is not None else {})
                else:
                    request_id = _validate_response(message)
                    if request_id not in self._client_requests:
                        raise ValueError("server response has no pending client request")
                    self._client_requests.remove(request_id)
            return _canonical(message), None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"


def _object(raw: str) -> dict[str, object]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("message is not JSON") from exc
    if type(value) is not dict:
        raise ValueError("message is not a JSON object")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _validate_method_message(
    message: dict[str, object],
    *,
    allowed_metadata: frozenset[str] = frozenset(),
) -> None:
    expected = {"method"}
    if "params" in message:
        expected.add("params")
    if "id" in message:
        expected.add("id")
    unexpected = set(message) - expected
    if not unexpected <= allowed_metadata:
        raise ValueError("method message has an invalid shape")
    method = message.get("method")
    if type(method) is not str or not method:
        raise ValueError("method must be a non-empty string")
    if "params" in message and message["params"] is not None:
        if type(message["params"]) is not dict:
            raise ValueError("params must be an object or null")
    if "id" in message:
        _message_id(message)
    if "emittedAtMs" in message:
        emitted_at_ms = message["emittedAtMs"]
        if type(emitted_at_ms) is not int or emitted_at_ms < 0:
            raise ValueError("emittedAtMs must be a non-negative integer")


def _validate_response(message: dict[str, object]) -> RpcId:
    result = "result" in message
    error = "error" in message
    if result == error:
        raise ValueError("response must contain exactly one result or error")
    expected = {"id", "result" if result else "error"}
    if set(message) != expected:
        raise ValueError("response has an invalid shape")
    if error and type(message["error"]) is not dict:
        raise ValueError("response error must be an object")
    return _message_id(message)


def _message_id(message: dict[str, object]) -> RpcId:
    value = message.get("id")
    if type(value) not in {str, int} or value == "":
        raise ValueError("id must be a non-empty string or an integer")
    return value


def _canonical(message: dict[str, object]) -> str:
    return json.dumps(
        message,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
