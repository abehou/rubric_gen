from __future__ import annotations

import http.client
import json
from pathlib import Path
from typing import Any

import pytest

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


@pytest.mark.parametrize("failure", [
    http.client.IncompleteRead(b"partial"),
    http.client.RemoteDisconnected("connection closed"),
    ConnectionResetError("connection reset"),
    TimeoutError("request timed out"),
])
def test_gemini_transport_failures_have_retryable_runtime_error_contract(
    monkeypatch: Any, failure: Exception,
) -> None:
    class BrokenResponse(_Response):
        def read(self) -> bytes:
            raise failure

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini.urllib.request, "urlopen", lambda *_args, **_kwargs: BrokenResponse())
    with pytest.raises(RuntimeError, match="Gemini API request failed") as caught:
        gemini.GeminiClient(model="gemini-test").generate_content("hello")
    assert caught.value.__cause__ is failure


def test_audit_identities_include_gemini_transport(monkeypatch: Any) -> None:
    from rubric_gen.detection.runner import scoring_implementation_sha256
    from rubric_gen.submission_revision.evaluation.jobs import _evaluation_implementation_sha256

    hashes = (scoring_implementation_sha256, _evaluation_implementation_sha256)
    before = [function() for function in hashes]
    read_bytes = Path.read_bytes
    target = Path(gemini.__file__).resolve()

    def modified(path: Path) -> bytes:
        value = read_bytes(path)
        return value + b"\n# changed transport\n" if path.resolve() == target else value

    monkeypatch.setattr(Path, "read_bytes", modified)
    assert all(function() != old for function, old in zip(hashes, before, strict=True))
