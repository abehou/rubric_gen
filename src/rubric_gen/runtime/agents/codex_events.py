"""Translate Codex app-server notifications into benchmark trajectory events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def notification_event(
    notification: Any,
    latest_usage: dict[str, object] | None,
    *,
    session_id: str,
) -> tuple[dict[str, object] | None, dict[str, object] | None]:
    method = getattr(notification, "method", "")
    payload = _json_payload(getattr(notification, "payload", {}))
    if method == "turn/started":
        return None, None
    if method in {"item/started", "item/completed"}:
        return _item_event(method, payload, session_id), None
    if method == "thread/tokenUsage/updated":
        return None, _usage(payload)
    if method == "error":
        return _error_event(payload), None
    if method == "turn/completed":
        return _completed_event(payload, latest_usage, session_id), None
    if not method:
        return None, None
    return (
        {
            "type": f"codex.{method.replace('/', '.')}",
            "payload": payload,
        },
        None,
    )


def trajectory_errors(stream_path: Path) -> list[str]:
    errors: list[str] = []
    for line in stream_path.read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        status = event.get("status")
        if event_type == "error":
            errors.append(f"trajectory_error: {event.get('message') or 'unknown'}")
        if event_type == "turn.completed" and status != "completed":
            errors.append(f"trajectory_turn_status: {status}")
    return errors


def _item_event(
    method: str,
    payload: dict[str, object],
    session_id: str,
) -> dict[str, object]:
    item = payload.get("item")
    if isinstance(item, dict):
        item = _normalize_item(item)
    return {
        "type": method.replace("/", "."),
        "thread_id": payload.get("thread_id", session_id),
        "turn_id": payload.get("turn_id"),
        "item": item,
    }


def _usage(payload: dict[str, object]) -> dict[str, object] | None:
    token_usage = payload.get("token_usage")
    total = token_usage.get("total") if isinstance(token_usage, dict) else None
    return total if isinstance(total, dict) else None


def _error_event(payload: dict[str, object]) -> dict[str, object]:
    error = payload.get("error")
    message = error.get("message") if isinstance(error, dict) else error
    will_retry = payload.get("will_retry") is True
    return {
        "type": "transport.retry" if will_retry else "error",
        "phase": "provider",
        "message": str(message or "unknown Codex error"),
        "will_retry": will_retry,
    }


def _completed_event(
    payload: dict[str, object],
    latest_usage: dict[str, object] | None,
    session_id: str,
) -> dict[str, object]:
    value = payload.get("turn")
    turn = value if isinstance(value, dict) else {}
    event: dict[str, object] = {
        "type": "turn.completed",
        "thread_id": payload.get("thread_id", session_id),
        "turn_id": turn.get("id"),
        "status": turn.get("status"),
    }
    if latest_usage is not None:
        event["usage"] = latest_usage
    if turn.get("error") is not None:
        event["error"] = turn["error"]
    return event


def _json_payload(payload: Any) -> dict[str, object]:
    if isinstance(payload, dict):
        return payload
    dump = getattr(payload, "model_dump", None)
    if dump is None:
        params = getattr(payload, "params", None)
        return params if isinstance(params, dict) else {}
    value = dump(mode="json", by_alias=False, exclude_none=True)
    return value if isinstance(value, dict) else {}


def _normalize_item(item: dict[str, object]) -> dict[str, object]:
    root = item.get("root")
    if isinstance(root, dict):
        item = root
    normalized = dict(item)
    item_type = normalized.get("type")
    if isinstance(item_type, str):
        normalized["type"] = _snake_case(item_type)
    return normalized


def _snake_case(value: str) -> str:
    result: list[str] = []
    for char in value:
        if char.isupper():
            result.extend(("_", char.lower()))
        else:
            result.append(char)
    return "".join(result).lstrip("_")
