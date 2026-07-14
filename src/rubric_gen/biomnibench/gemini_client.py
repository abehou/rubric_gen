"""Minimal HTTP client for the Gemini generateContent API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_GENERATE_CONTENT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class GeminiGenerateContentResponse:
    """One Gemini response with the provider's serving identity intact."""

    text: str
    model_version: str
    response_id: str

    def __post_init__(self) -> None:
        for field_name in ("text", "model_version", "response_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")


class GeminiClient:
    """Small synchronous client for Gemini text generation."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV,
        base_url: str = GEMINI_GENERATE_CONTENT_BASE_URL,
        timeout_seconds: int = 600,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate_content(self, prompt: str) -> str:
        return self.response_text(self._generate_content_payload(prompt))

    def generate_content_response(
        self,
        prompt: str,
    ) -> GeminiGenerateContentResponse:
        """Generate text while retaining the provider's response identity."""

        return self.response_with_metadata(self._generate_content_payload(prompt))

    def _generate_content_payload(self, prompt: str) -> dict[str, Any]:
        api_key = self.api_key()
        request = urllib.request.Request(
            self.generate_content_url(api_key),
            data=json.dumps(self.request_body(prompt)).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                response_payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(
                f"Gemini API request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc
        if not isinstance(response_payload, dict):
            raise RuntimeError("Gemini API response must be a JSON object")
        return response_payload

    def request_body(self, prompt: str) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if key:
            return key
        if self.api_key_env == DEFAULT_GEMINI_API_KEY_ENV:
            fallback = os.environ.get("GOOGLE_API_KEY")
            if fallback:
                return fallback
        raise RuntimeError(
            f"Missing Gemini API key. Set {self.api_key_env}"
            + (
                " or GOOGLE_API_KEY."
                if self.api_key_env == DEFAULT_GEMINI_API_KEY_ENV
                else "."
            )
        )

    def generate_content_url(self, api_key: str) -> str:
        model_name = (
            self.model if self.model.startswith("models/") else f"models/{self.model}"
        )
        quoted_model = urllib.parse.quote(model_name, safe="/")
        quoted_key = urllib.parse.quote(api_key, safe="")
        return f"{self.base_url}/{quoted_model}:generateContent?key={quoted_key}"

    def response_text(self, payload: dict[str, Any]) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Gemini API response did not contain candidate text: {payload}"
            ) from exc
        text = "".join(
            str(part.get("text", "")) for part in parts if isinstance(part, dict)
        )
        if not text.strip():
            raise RuntimeError(f"Gemini API response contained empty text: {payload}")
        return text

    def response_with_metadata(
        self,
        payload: dict[str, Any],
    ) -> GeminiGenerateContentResponse:
        text = self.response_text(payload)
        metadata: dict[str, str] = {}
        for json_name, field_name in (
            ("modelVersion", "model_version"),
            ("responseId", "response_id"),
        ):
            value = payload.get(json_name)
            if type(value) is not str or not value.strip():
                error = RuntimeError(
                    f"Gemini API response {json_name} must be a non-empty string"
                )
                error.raw_response = text  # type: ignore[attr-defined]
                raise error
            metadata[field_name] = value
        return GeminiGenerateContentResponse(text=text, **metadata)
