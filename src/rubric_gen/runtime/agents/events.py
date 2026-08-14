"""Agent stream event helpers."""

from __future__ import annotations

from typing import Any


def event_text(event: Any) -> str | None:
    """Return a compact human-readable view of one provider stream event."""
    if not isinstance(event, dict):
        return None

    candidates: list[str] = []
    stack: list[Any] = [event]
    interesting_keys = {
        "text",
        "content",
        "message",
        "thought",
        "name",
        "command",
        "status",
        "type",
    }
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in interesting_keys and isinstance(child, str) and child.strip():
                    candidates.append(f"{key}={child.strip()}")
                elif isinstance(child, (dict, list)):
                    stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)
    return " | ".join(candidates[:6]) if candidates else None
