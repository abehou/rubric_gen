"""Exact provider-call replay for rubric evolution."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.artifacts import make_read_only
from rubric_gen.submission_revision.evolution_provider import (
    ProviderContract,
    StructuredProviderOutput,
    deserialize_output,
    serialize_output,
)
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_sha256,
    load_json_object,
)


_LEDGER_KIND = "criterion-elicitation-provider-ledger"
_LEDGER_KEYS = frozenset({
    "kind",
    "implementation_identity",
    "context",
    "attempts",
})
_LEDGER_ENTRY_KEYS = frozenset({
    "call_index",
    "role",
    "attempt",
    "request",
    "request_sha256",
    "state",
    "output",
    "error",
})
_LEDGER_ERROR_KEYS = frozenset({"type", "message"})
_ROLES = frozenset({"differences", "criteria", "editor"})


class RecordedProviderFailure(RuntimeError):
    """Report one recorded provider failure that a stage can retry."""


class ProviderLedger:
    """Record provider calls before dispatch and replay their exact prefix."""

    def __init__(
        self,
        path: Path,
        *,
        context: dict[str, object],
        implementation_identity: dict[str, str],
    ) -> None:
        self.path = path
        self.context = context
        self.implementation_identity = implementation_identity
        self._value, self.existed = self._load()
        self._position = 0

    @property
    def _entries(self) -> list[object]:
        entries = self._value["attempts"]
        assert isinstance(entries, list)
        return entries

    def output(
        self,
        *,
        role: str,
        attempt: int,
        request: dict[str, object],
        generate: Callable[[], StructuredProviderOutput],
        contract: ProviderContract,
    ) -> StructuredProviderOutput:
        request_sha256 = canonical_sha256(request)
        if self._position < len(self._entries):
            return self._replayed_output(
                role=role,
                attempt=attempt,
                request=request,
                request_sha256=request_sha256,
                contract=contract,
            )
        if self.existed and self._position != len(self._entries):
            raise RuntimeError("provider ledger cursor is not at its append boundary")
        if self.path.exists() and self.path.stat().st_mode & 0o222 == 0:
            raise RuntimeError("sealed provider ledger cannot dispatch another call")
        return self._recorded_output(
            role=role,
            attempt=attempt,
            request=request,
            request_sha256=request_sha256,
            generate=generate,
            contract=contract,
        )

    def require_consumed(self) -> None:
        if self._position != len(self._entries):
            raise RuntimeError("provider ledger contains unreachable calls")

    def seal_failed_stage(self) -> None:
        if self.existed:
            self.require_consumed()
        make_read_only(self.path)

    def seal(self) -> None:
        make_read_only(self.path)

    def _load(self) -> tuple[dict[str, object], bool]:
        if not os.path.lexists(self.path):
            return {
                "kind": _LEDGER_KIND,
                "implementation_identity": self.implementation_identity,
                "context": self.context,
                "attempts": [],
            }, False
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimeError("provider ledger is not a regular file")
        value = self._read_exact_json()
        if set(value) != _LEDGER_KEYS:
            raise RuntimeError("provider ledger has invalid fields")
        if (
            value["kind"] != _LEDGER_KIND
            or value["implementation_identity"] != self.implementation_identity
            or value["context"] != self.context
        ):
            raise RuntimeError("provider ledger identity changed")
        attempts = value["attempts"]
        if not isinstance(attempts, list) or not attempts:
            raise RuntimeError("existing provider ledger has no dispatched call")
        for index, entry in enumerate(attempts, start=1):
            self._validate_entry(entry, index)
        return value, True

    def _replayed_output(
        self,
        *,
        role: str,
        attempt: int,
        request: dict[str, object],
        request_sha256: str,
        contract: ProviderContract,
    ) -> StructuredProviderOutput:
        entry = self._entries[self._position]
        assert isinstance(entry, dict)
        if (
            entry["role"] != role
            or entry["attempt"] != attempt
            or entry["request"] != request
            or entry["request_sha256"] != request_sha256
        ):
            raise RuntimeError(
                "provider ledger prefix differs from the next exact request"
            )
        self._position += 1
        if entry["state"] == "failed":
            error = entry["error"]
            assert isinstance(error, dict)
            raise RecordedProviderFailure(
                f"{role} provider call failed: {error['type']}: "
                f"{error['message']}"
            )
        if entry["state"] != "completed":
            raise RuntimeError(
                "a prior provider dispatch did not publish a complete response"
            )
        output = deserialize_output(entry["output"])
        contract.validate_output(output)
        return output

    def _recorded_output(
        self,
        *,
        role: str,
        attempt: int,
        request: dict[str, object],
        request_sha256: str,
        generate: Callable[[], StructuredProviderOutput],
        contract: ProviderContract,
    ) -> StructuredProviderOutput:
        entry: dict[str, object] = {
            "call_index": len(self._entries) + 1,
            "role": role,
            "attempt": attempt,
            "request": request,
            "request_sha256": request_sha256,
            "state": "dispatched",
            "output": None,
            "error": None,
        }
        self._entries.append(entry)
        self._persist()
        try:
            output = generate()
            contract.validate_output(output)
        except Exception as exc:
            entry["state"] = "failed"
            entry["error"] = {
                "type": type(exc).__name__,
                "message": str(exc) or type(exc).__name__,
            }
            self._persist()
            self._position += 1
            raise RecordedProviderFailure(
                f"{role} provider call failed: {type(exc).__name__}: "
                f"{str(exc) or type(exc).__name__}"
            ) from exc
        entry["state"] = "completed"
        entry["output"] = serialize_output(output)
        self._persist()
        self._position += 1
        return output

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.path, self._value)
        with self.path.open("rb") as stream:
            os.fsync(stream.fileno())

    def _read_exact_json(self) -> dict[str, object]:
        try:
            return load_json_object(
                self.path.read_text(encoding="utf-8"),
                str(self.path),
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError(f"artifact is invalid: {self.path}") from exc

    @staticmethod
    def _validate_entry(value: object, call_index: int) -> None:
        if not isinstance(value, dict) or set(value) != _LEDGER_ENTRY_KEYS:
            raise RuntimeError("provider ledger entry has invalid fields")
        if type(value["call_index"]) is not int or value["call_index"] != call_index:
            raise RuntimeError("provider ledger call order is invalid")
        if type(value["role"]) is not str or value["role"] not in _ROLES:
            raise RuntimeError("provider ledger role is invalid")
        if type(value["attempt"]) is not int or value["attempt"] < 1:
            raise RuntimeError("provider ledger attempt is invalid")
        if not isinstance(value["request"], dict):
            raise RuntimeError("provider ledger request is invalid")
        if value["request_sha256"] != canonical_sha256(value["request"]):
            raise RuntimeError("provider ledger request hash is invalid")
        state = value["state"]
        if state not in {"dispatched", "completed", "failed"}:
            raise RuntimeError("provider ledger state is invalid")
        if state == "completed":
            if value["output"] is None or value["error"] is not None:
                raise RuntimeError("completed provider ledger entry is invalid")
            deserialize_output(value["output"])
            return
        if state == "failed":
            error = value["error"]
            if (
                value["output"] is not None
                or not isinstance(error, dict)
                or set(error) != _LEDGER_ERROR_KEYS
                or type(error["type"]) is not str
                or not error["type"]
                or type(error["message"]) is not str
                or not error["message"]
            ):
                raise RuntimeError("failed provider ledger entry is invalid")
            return
        if value["output"] is not None or value["error"] is not None:
            raise RuntimeError("dispatched provider ledger entry is invalid")
