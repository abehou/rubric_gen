"""Provider-neutral structured language-model generation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import threading
from dataclasses import dataclass, field

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.runtime.integrations.gemini import GeminiClient
from rubric_gen.runtime.pricing import (
    ANTHROPIC_PRICES_PER_MILLION,
    GEMINI_PRICES_PER_MILLION,
    OPENAI_PRICES_PER_MILLION,
)


DEFAULT_MAX_OUTPUT_TOKENS = 4_096
HOSTED_REQUEST_TIMEOUT_SECONDS = 600.0
TOKEN_COUNT_TIMEOUT_SECONDS = 120.0
OPENAI_REASONING_EFFORT = "none"
OPENAI_TEXT_VERBOSITY = "low"
ANTHROPIC_EFFORT = "low"
GEMINI_THINKING_LEVEL = "low"
OPENAI_EXPLICIT_PROMPT_CACHE_MODELS = frozenset({
    "gpt-5.6-luna",
    "gpt-5.6-sol",
})
_TOKEN_COUNTER_CLIENTS: dict[tuple[str, str], object] = {}
_TOKEN_COUNTER_CLIENTS_LOCK = threading.Lock()


def anthropic_schema(value: object) -> object:
    """Render the supported Anthropic structured-output schema subset."""
    if isinstance(value, dict):
        return {
            key: anthropic_schema(child)
            for key, child in value.items()
            if key not in {"minimum", "maximum"}
        }
    if isinstance(value, list):
        return [anthropic_schema(child) for child in value]
    return value


@dataclass(frozen=True)
class StructuredRequest:
    """Provider-neutral request with an explicitly cacheable static prefix."""

    instructions: str
    evidence: str
    schema_name: str
    schema: dict[str, object]
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    prompt_layout: str = "split_roles"

    def __post_init__(self) -> None:
        if self.prompt_layout not in {"split_roles", "cached_user_prefix"}:
            raise ValueError("model request prompt layout is invalid")

    def flat_prompt(self) -> str:
        separator = "\n" if self.prompt_layout == "cached_user_prefix" else "\n\n"
        return self.instructions.rstrip() + separator + self.evidence.lstrip()

    def openai_input(self, model: str) -> list[dict[str, object]]:
        cache_breakpoint = (
            {"prompt_cache_breakpoint": {"mode": "explicit"}}
            if openai_supports_explicit_prompt_cache(model)
            else {}
        )
        if self.prompt_layout == "cached_user_prefix":
            return [{
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": self.instructions,
                        **cache_breakpoint,
                    },
                    {"type": "input_text", "text": self.evidence},
                ],
            }]
        return [
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": self.instructions,
                    **cache_breakpoint,
                }],
            },
            {"role": "user", "content": self.evidence},
        ]

    def text_config(self) -> dict[str, object]:
        return {
            "verbosity": OPENAI_TEXT_VERBOSITY,
            "format": {
                "type": "json_schema",
                "name": self.schema_name,
                "strict": True,
                "schema": self.schema,
            },
        }

    def anthropic_system(self) -> list[dict[str, object]] | None:
        if self.prompt_layout == "cached_user_prefix":
            return None
        return [{
            "type": "text",
            "text": self.instructions,
            "cache_control": {"type": "ephemeral"},
        }]

    def anthropic_messages(self) -> list[dict[str, object]]:
        if self.prompt_layout == "cached_user_prefix":
            return [{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": self.instructions,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": self.evidence},
                ],
            }]
        return [{"role": "user", "content": self.evidence}]

    def vllm_messages(self) -> list[dict[str, str]]:
        if self.prompt_layout == "cached_user_prefix":
            return [{"role": "user", "content": self.flat_prompt()}]
        return [
            {"role": "system", "content": self.instructions},
            {"role": "user", "content": self.evidence},
        ]

    def prompt_cache_key(self) -> str:
        return "rubric-gen-" + sha256_text(
            self.prompt_layout + "\0" + self.instructions
        )[:48]


@dataclass(frozen=True)
class GenerationResult:
    text: str
    provider: str
    requested_model: str
    effective_model: str
    response_id: str
    request_parameters: dict[str, object]
    provider_metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "text", "provider", "requested_model", "effective_model", "response_id"
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"generation {field_name} must be a non-empty string")

    def provenance(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "requested_model": self.requested_model,
            "effective_model": self.effective_model,
            "response_id": self.response_id,
            "request_parameters": self.request_parameters,
            "provider_metadata": self.provider_metadata,
        }


def openai_supports_explicit_prompt_cache(model: str) -> bool:
    """Return whether the OpenAI model accepts explicit prompt-cache fields."""

    return model in OPENAI_EXPLICIT_PROMPT_CACHE_MODELS


def openai_prompt_cache_arguments(
    model: str,
    request: StructuredRequest,
) -> dict[str, object]:
    if not openai_supports_explicit_prompt_cache(model):
        return {}
    return {
        "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "prompt_cache_key": request.prompt_cache_key(),
    }


def request_parameters_for_model(
    model: str,
    *,
    base_url: str | None = None,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> dict[str, object]:
    if base_url is not None:
        return {
            "provider": "vllm",
            "requested_model": model,
            "base_url": base_url.rstrip("/") + "/",
            "max_tokens": max_output_tokens,
            "temperature": 0,
            "client_timeout_seconds": HOSTED_REQUEST_TIMEOUT_SECONDS,
            "client_max_retries": 0,
            "response_format": "json_schema",
        }
    if model.startswith("gemini"):
        return {
            "provider": "google",
            "requested_model": model,
            "temperature": 0.2,
            "thinking_level": GEMINI_THINKING_LEVEL,
            "max_output_tokens": max_output_tokens,
            "response_format": "json_schema",
            "prompt_cache": {"mode": "provider_implicit", "stable_prefix": True},
        }
    if model.startswith("claude"):
        return {
            "provider": "anthropic",
            "requested_model": model,
            "max_tokens": max_output_tokens,
            "effort": ANTHROPIC_EFFORT,
            "client_timeout_seconds": HOSTED_REQUEST_TIMEOUT_SECONDS,
            "client_max_retries": 0,
            "prompt_cache": {"ttl": "5m"},
            "response_format": "json_schema",
        }
    parameters: dict[str, object] = {
        "provider": "openai",
        "requested_model": model,
        "max_output_tokens": max_output_tokens,
        "reasoning_effort": OPENAI_REASONING_EFFORT,
        "text_verbosity": OPENAI_TEXT_VERBOSITY,
        "client_timeout_seconds": HOSTED_REQUEST_TIMEOUT_SECONDS,
        "client_max_retries": 0,
        "response_format": "json_schema",
    }
    if openai_supports_explicit_prompt_cache(model):
        parameters.update({
            "prompt_cache": {"mode": "explicit", "ttl": "30m"},
            "prompt_cache_key": "sha256-of-layout-and-stable-prefix",
        })
    return parameters


def metadata_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): metadata_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [metadata_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return metadata_value(model_dump())
    as_dict = getattr(value, "to_dict", None)
    if callable(as_dict):
        return metadata_value(as_dict())
    return str(value)


def _response_identity(response: object, requested_model: str) -> tuple[str, str]:
    effective_model = getattr(response, "model", None)
    response_id = getattr(response, "id", None)
    if type(effective_model) is not str or not effective_model.strip():
        raise RuntimeError(
            f"provider response for {requested_model} omitted the effective model"
        )
    if type(response_id) is not str or not response_id.strip():
        raise RuntimeError(
            f"provider response for {requested_model} omitted the response ID"
        )
    return effective_model, response_id


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def estimate_input_tokens(model: str, request: StructuredRequest) -> int:
    """Conservative local estimate used to choose initial chunk boundaries."""

    payload = json.dumps(
        {
            "input": request.openai_input(model),
            "text": request.text_config(),
            "reasoning": {"effort": OPENAI_REASONING_EFFORT},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return max(math.ceil(len(payload) / 2.8), math.ceil(len(payload.encode()) / 3.0))


def _token_counter_client(provider: str, api_key: str) -> object:
    identity = (provider, hashlib.sha256(api_key.encode("utf-8")).hexdigest())
    with _TOKEN_COUNTER_CLIENTS_LOCK:
        existing = _TOKEN_COUNTER_CLIENTS.get(identity)
        if existing is not None:
            return existing
        if provider == "openai":
            from openai import OpenAI

            client: object = OpenAI(
                api_key=api_key,
                timeout=TOKEN_COUNT_TIMEOUT_SECONDS,
                max_retries=0,
            )
        elif provider == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(
                api_key=api_key,
                timeout=TOKEN_COUNT_TIMEOUT_SECONDS,
                max_retries=0,
            )
        elif provider == "google":
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(attempts=0)
                ),
            )
        else:
            raise ValueError(f"unsupported token counter provider: {provider}")
        _TOKEN_COUNTER_CLIENTS[identity] = client
        return client


def count_input_tokens(model: str, request: StructuredRequest) -> int:
    """Use hosted token counters before any paid generation request."""

    if model in OPENAI_PRICES_PER_MILLION:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY must be set for cost preflight")
        client = _token_counter_client("openai", key)
        response = client.responses.input_tokens.count(  # type: ignore[attr-defined]
            model=model,
            input=request.openai_input(model),
            reasoning={"effort": OPENAI_REASONING_EFFORT},
            text={"format": request.text_config()["format"]},
            truncation="disabled",
        )
        value = getattr(response, "input_tokens", None)
        provider = "OpenAI"
    elif model in ANTHROPIC_PRICES_PER_MILLION:
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set for cost preflight")
        client = _token_counter_client("anthropic", key)
        arguments: dict[str, object] = {
            "model": model,
            "messages": request.anthropic_messages(),
            "output_config": {
                "effort": ANTHROPIC_EFFORT,
                "format": {
                    "type": "json_schema",
                    "schema": anthropic_schema(request.schema),
                },
            },
        }
        if request.anthropic_system() is not None:
            arguments["system"] = request.anthropic_system()
        response = client.messages.count_tokens(  # type: ignore[attr-defined]
            **arguments
        )
        value = getattr(response, "input_tokens", None)
        provider = "Anthropic"
    elif model in GEMINI_PRICES_PER_MILLION:
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY must be set for cost preflight")
        client = _token_counter_client("google", key)
        response = client.models.count_tokens(  # type: ignore[attr-defined]
            model=model,
            contents=request.flat_prompt(),
        )
        content_tokens = getattr(response, "total_tokens", None)
        if type(content_tokens) is not int or content_tokens <= 0:
            raise RuntimeError(
                "Gemini token counter returned an invalid count: "
                f"{content_tokens!r}"
            )
        # Gemini Developer API's countTokens method counts contents but does not
        # accept the response schema. Reserve one token per serialized schema
        # byte so structured-output overhead cannot be silently omitted.
        schema_reservation = len(
            json.dumps(
                request.schema,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        value = content_tokens + schema_reservation
        provider = "Gemini"
    else:
        return estimate_input_tokens(model, request)
    if type(value) is not int or value <= 0:
        raise RuntimeError(
            f"{provider} token counter returned an invalid count: {value!r}"
        )
    return value


def generate_structured(
    model: str,
    request_value: StructuredRequest,
) -> GenerationResult:
    request = request_parameters_for_model(
        model, max_output_tokens=request_value.max_output_tokens
    )
    if model.startswith("gemini"):
        response = GeminiClient(model=model).generate_content_response(
            request_value.flat_prompt(),
            response_schema=request_value.schema,
            thinking_level=GEMINI_THINKING_LEVEL,
            max_output_tokens=request_value.max_output_tokens,
        )
        return GenerationResult(
            text=response.text,
            provider="google",
            requested_model=model,
            effective_model=response.model_version,
            response_id=response.response_id,
            request_parameters=request,
            provider_metadata={
                "client": "rubric_gen.runtime.integrations.gemini",
                "usage": metadata_value(
                    getattr(response, "usage_metadata", None)
                ),
            },
        )
    if model.startswith("claude"):
        from anthropic import Anthropic
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set")
        arguments = {
            "model": model,
            "max_tokens": request_value.max_output_tokens,
            "messages": request_value.anthropic_messages(),
            "output_config": {
                "effort": ANTHROPIC_EFFORT,
                "format": {
                    "type": "json_schema",
                    "schema": anthropic_schema(request_value.schema),
                },
            },
        }
        if request_value.anthropic_system() is not None:
            arguments["system"] = request_value.anthropic_system()
        response = Anthropic(
            api_key=key,
            timeout=HOSTED_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        ).messages.create(**arguments)
        text = "\n".join(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )
        if not text:
            raise RuntimeError("Anthropic returned an empty response")
        effective_model, response_id = _response_identity(response, model)
        return GenerationResult(
            text=text,
            provider="anthropic",
            requested_model=model,
            effective_model=effective_model,
            response_id=response_id,
            request_parameters=request,
            provider_metadata={
                "sdk_version": _package_version("anthropic"),
                "stop_reason": metadata_value(getattr(response, "stop_reason", None)),
                "usage": metadata_value(getattr(response, "usage", None)),
            },
        )
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    response = OpenAI(
        api_key=key,
        timeout=HOSTED_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ).responses.create(
        model=model,
        input=request_value.openai_input(model),
        max_output_tokens=request_value.max_output_tokens,
        reasoning={"effort": OPENAI_REASONING_EFFORT},
        text=request_value.text_config(),
        truncation="disabled",
        store=False,
        **openai_prompt_cache_arguments(model, request_value),
    )
    if not response.output_text:
        raise RuntimeError("OpenAI returned an empty response")
    effective_model, response_id = _response_identity(response, model)
    return GenerationResult(
        text=response.output_text,
        provider="openai",
        requested_model=model,
        effective_model=effective_model,
        response_id=response_id,
        request_parameters=request,
        provider_metadata={
            "sdk_version": _package_version("openai"),
            "created_at": metadata_value(getattr(response, "created_at", None)),
            "service_tier": metadata_value(getattr(response, "service_tier", None)),
            "usage": metadata_value(getattr(response, "usage", None)),
        },
    )


def generate_structured_vllm(
    model: str, request_value: StructuredRequest, base_url: str
) -> GenerationResult:
    from openai import OpenAI

    response = OpenAI(
        base_url=base_url.rstrip("/") + "/",
        api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
        timeout=HOSTED_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ).chat.completions.create(
        model=model,
        messages=request_value.vllm_messages(),
        max_tokens=request_value.max_output_tokens,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": request_value.schema_name,
                "strict": True,
                "schema": request_value.schema,
            },
        },
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("vLLM returned an empty response")
    effective_model, response_id = _response_identity(response, model)
    return GenerationResult(
        text=content,
        provider="vllm",
        requested_model=model,
        effective_model=effective_model,
        response_id=response_id,
        request_parameters=request_parameters_for_model(
            model,
            base_url=base_url,
            max_output_tokens=request_value.max_output_tokens,
        ),
        provider_metadata={
            "openai_client_version": _package_version("openai"),
            "created": metadata_value(getattr(response, "created", None)),
            "system_fingerprint": metadata_value(
                getattr(response, "system_fingerprint", None)
            ),
            "usage": metadata_value(getattr(response, "usage", None)),
        },
    )
