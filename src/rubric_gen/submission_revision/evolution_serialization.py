"""Canonical JSON helpers for rubric generation."""

from __future__ import annotations

import json

from rubric_gen.artifacts.hashing import sha256_text


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_sha256(value: object) -> str:
    return sha256_text(canonical_json(value))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_object(text: str, context: str) -> dict[str, object]:
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{context} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a JSON object")
    return value
