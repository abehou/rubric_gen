"""Keep asynchronous command results inside their solver turn's completion."""
from __future__ import annotations

import json


class TurnCompletionBuffer:
    """Delay successful completion until commands already issued have exited.

    The model's completion payload is forwarded unchanged. The driver's existing
    turn deadline still applies while commands finish; errors and interruptions
    are forwarded immediately. No extra model turn or instruction is introduced.
    """

    def __init__(self) -> None:
        self._running: dict[tuple[str, str], set[str]] = {}
        self._completed: dict[tuple[str, str], str] = {}

    def accept(self, raw: str) -> tuple[str, ...]:
        value = json.loads(raw)
        method = value.get("method")
        params = value.get("params") or {}
        thread = params.get("threadId")
        turn = params.get("turnId")
        if method == "turn/completed":
            turn = params["turn"]["id"]
        if not isinstance(thread, str) or not isinstance(turn, str):
            return (raw,)
        key = (thread, turn)
        item = params.get("item") or {}
        if method == "item/started" and item.get("type") == "commandExecution":
            self._running.setdefault(key, set()).add(item["id"])
        elif method == "item/completed" and item.get("type") == "commandExecution":
            active = self._running.get(key)
            if active is not None:
                active.discard(item["id"])
                if not active:
                    self._running.pop(key)
                    if key in self._completed:
                        return (raw, self._completed.pop(key))
        elif method == "turn/completed":
            if params["turn"]["status"] == "completed" and self._running.get(key):
                self._completed[key] = raw
                return ()
            self._running.pop(key, None)
            self._completed.pop(key, None)
        return (raw,)
