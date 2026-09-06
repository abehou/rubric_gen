from __future__ import annotations

import json
from typing import Any

from rubric_gen.runtime.integrations import gemini


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}).encode()


def test_gemini_client_uses_certifi_ca_bundle(monkeypatch: Any) -> None:
    captured: dict[str, object] = {}
    context = object()

    def fake_create_default_context(*, cafile: str) -> object:
        captured["cafile"] = cafile
        return context

    def fake_urlopen(request: object, **kwargs: object) -> _Response:
        captured["request"] = request
        captured.update(kwargs)
        return _Response()

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini.certifi, "where", lambda: "/test/cacert.pem")
    monkeypatch.setattr(gemini.ssl, "create_default_context", fake_create_default_context)
    monkeypatch.setattr(gemini.urllib.request, "urlopen", fake_urlopen)

    result = gemini.GeminiClient(model="gemini-test", timeout_seconds=17).generate_content(
        "hello"
    )

    assert result == "OK"
    assert captured["cafile"] == "/test/cacert.pem"
    assert captured["context"] is context
    assert captured["timeout"] == 17
