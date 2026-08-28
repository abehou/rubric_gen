"""Structured provider boundary for rubric evolution."""

from __future__ import annotations

import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from numbers import Real

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
)


PROPOSER_MAX_OUTPUT_TOKENS = 32_768
MAX_SEMANTIC_REVIEW_OUTPUT_TOKENS = 32_768
PROPOSER_MAX_REQUEST_BYTES = 1024 * 1024
MAX_SEMANTIC_REVIEW_REQUEST_BYTES = 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 1_800.0
_REASONING_EFFORT = "low"
_TEXT_VERBOSITY = "low"
_COST_KEYS = frozenset({"cost_usd", "estimated_cost_usd", "cost_source"})
_GENERATION_KEYS = frozenset({
    "provider",
    "requested_model",
    "effective_model",
    "response_id",
    "request_parameters",
    "usage",
})


@dataclass(frozen=True)
class StructuredProviderOutput:
    """Store one structured response and its provider metadata."""

    response_text: str
    cost: dict[str, float | str | None]
    generation: dict[str, object]


ProviderOperation = Callable[..., StructuredProviderOutput]


@dataclass(frozen=True)
class ProviderContract:
    """Define and enforce one structured model-provider boundary."""

    model: str
    base_url: str | None
    max_output_tokens: int
    max_request_bytes: int
    service_tier: str | None

    def __post_init__(self) -> None:
        if type(self.model) is not str or not self.model.strip():
            raise ValueError("provider model must be nonempty")
        if self.base_url is not None and (
            type(self.base_url) is not str or not self.base_url.strip()
        ):
            raise ValueError("provider base URL must be nonempty")
        if type(self.max_output_tokens) is not int or self.max_output_tokens < 1:
            raise ValueError("provider output-token limit must be positive")
        if type(self.max_request_bytes) is not int or self.max_request_bytes < 1:
            raise ValueError("provider request-byte limit must be positive")
        if self.service_tier is not None and (
            type(self.service_tier) is not str or not self.service_tier.strip()
        ):
            raise ValueError("provider service tier must be nonempty")

    @property
    def provider(self) -> str:
        return "vllm" if self.base_url is not None else "openai"

    def record(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": (
                self.base_url.rstrip("/") + "/" if self.base_url else None
            ),
            "reasoning_effort": _REASONING_EFFORT,
            "text_verbosity": _TEXT_VERBOSITY,
            "max_output_tokens": self.max_output_tokens,
            "max_request_bytes": self.max_request_bytes,
            "client_timeout_seconds": _REQUEST_TIMEOUT_SECONDS,
            "service_tier": (
                self.service_tier if self.base_url is None else None
            ),
        }

    def request_identity(
        self,
        *,
        role: str,
        instructions: str,
        evidence: str,
        response_schema: dict[str, object],
        implementation_identity: dict[str, str],
    ) -> dict[str, object]:
        size = request_bytes(instructions, evidence, response_schema)
        if size > self.max_request_bytes:
            raise ValueError(
                f"{role} request is {size} UTF-8 bytes; "
                f"limit is {self.max_request_bytes}"
            )
        return {
            "role": role,
            "contract": self.record(),
            "prompt_sha256": sha256_text(instructions + "\0" + evidence),
            "response_schema_sha256": canonical_sha256(response_schema),
            "request_bytes": size,
            "implementation_identity": implementation_identity,
        }

    def validate_output(self, output: StructuredProviderOutput) -> None:
        if not isinstance(output, StructuredProviderOutput):
            raise RuntimeError("provider returned the wrong output type")
        if type(output.response_text) is not str or not output.response_text.strip():
            raise RuntimeError("provider returned empty structured output")
        if not _valid_cost(output.cost) or not _valid_generation(output.generation):
            raise RuntimeError("provider returned invalid usage metadata")
        if (
            output.generation["provider"] != self.provider
            or output.generation["requested_model"] != self.model
            or output.generation["effective_model"] != self.model
        ):
            raise RuntimeError("provider response differs from its configured model")

    def generate(
        self,
        *,
        instructions: str,
        evidence: str,
        response_schema: dict[str, object],
        request_context: str,
        schema_name: str,
    ) -> StructuredProviderOutput:
        return generate_structured(
            model=self.model,
            base_url=self.base_url,
            service_tier=(
                self.service_tier if self.base_url is None else None
            ),
            instructions=instructions,
            evidence=evidence,
            response_schema=response_schema,
            max_output_tokens=self.max_output_tokens,
            max_request_bytes=self.max_request_bytes,
            request_context=request_context,
            schema_name=schema_name,
        )


def request_bytes(
    instructions: str,
    evidence: str,
    response_schema: dict[str, object],
) -> int:
    return len(
        (instructions + "\0" + evidence + "\0" + canonical_json(response_schema))
        .encode("utf-8")
    )


def attempt_record(
    output: StructuredProviderOutput,
    *,
    attempt: int,
) -> dict[str, object]:
    return {
        "attempt": attempt,
        "response_sha256": sha256_text(output.response_text),
        "cost": output.cost,
        "generation": output.generation,
    }


def failed_attempt_record(attempt: int, error: str) -> dict[str, object]:
    """Return one auditable stage attempt with no provider response."""

    return {
        "attempt": attempt,
        "response_sha256": None,
        "cost": None,
        "generation": None,
        "validation_error": error,
    }


def serialize_output(output: StructuredProviderOutput) -> dict[str, object]:
    return {
        "response": output.response_text,
        "cost": output.cost,
        "generation": output.generation,
    }


def deserialize_output(value: object) -> StructuredProviderOutput:
    if not isinstance(value, dict) or set(value) != {
        "response", "cost", "generation"
    }:
        raise RuntimeError("provider ledger output has invalid fields")
    response = value["response"]
    cost = value["cost"]
    generation = value["generation"]
    if type(response) is not str or not response.strip():
        raise RuntimeError("provider ledger response is empty")
    if not _valid_cost(cost) or not _valid_generation(generation):
        raise RuntimeError("provider ledger output metadata is invalid")
    assert isinstance(cost, dict) and isinstance(generation, dict)
    return StructuredProviderOutput(
        response_text=response,
        cost=dict(cost),
        generation=dict(generation),
    )


def _valid_cost(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _COST_KEYS:
        return False
    for key in ("cost_usd", "estimated_cost_usd"):
        item = value[key]
        if item is not None and (
            isinstance(item, bool)
            or not isinstance(item, Real)
            or not math.isfinite(float(item))
            or float(item) < 0
        ):
            return False
    source = value["cost_source"]
    return (
        source is None
        and value["cost_usd"] is None
        and value["estimated_cost_usd"] is None
    ) or (type(source) is str and bool(source.strip()))


def _valid_generation(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _GENERATION_KEYS:
        return False
    return (
        all(
            type(value[key]) is str and bool(value[key].strip())
            for key in (
                "provider", "requested_model", "effective_model", "response_id"
            )
        )
        and isinstance(value["request_parameters"], dict)
        and bool(value["request_parameters"])
        and (value["usage"] is None or isinstance(value["usage"], dict))
    )


def generate_structured(
    *,
    model: str,
    base_url: str | None,
    service_tier: str | None,
    instructions: str,
    evidence: str,
    response_schema: dict[str, object],
    max_output_tokens: int,
    max_request_bytes: int,
    request_context: str,
    schema_name: str,
) -> StructuredProviderOutput:
    size = request_bytes(instructions, evidence, response_schema)
    if size > max_request_bytes:
        raise ValueError(
            f"{request_context} request is {size} UTF-8 bytes; "
            f"limit is {max_request_bytes}"
        )
    from openai import OpenAI

    if base_url is not None:
        normalized_base_url = base_url.rstrip("/") + "/"
        response = OpenAI(
            base_url=normalized_base_url,
            api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
            timeout=_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        ).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": evidence},
            ],
            max_tokens=max_output_tokens,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            },
        )
        text = response.choices[0].message.content or ""
        if not text:
            raise RuntimeError("vLLM returned an empty structured response")
        effective_model = getattr(response, "model", None)
        response_id = getattr(response, "id", None)
        if type(effective_model) is not str or not effective_model.strip():
            raise RuntimeError("vLLM response has no effective model")
        if type(response_id) is not str or not response_id.strip():
            raise RuntimeError("vLLM response has no response ID")
        usage = _jsonable(getattr(response, "usage", None))
        return StructuredProviderOutput(
            response_text=text,
            cost=_cost_from_usage(usage, model=model, service_tier=None),
            generation={
                "provider": "vllm",
                "requested_model": model,
                "effective_model": effective_model,
                "response_id": response_id,
                "request_parameters": {
                    "base_url": normalized_base_url,
                    "max_tokens": max_output_tokens,
                    "temperature": 0,
                    "client_timeout_seconds": _REQUEST_TIMEOUT_SECONDS,
                    "client_max_retries": 0,
                    "response_format": "json_schema",
                },
                "usage": usage,
            },
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(f"OPENAI_API_KEY must be set for the {request_context}")
    arguments: dict[str, object] = {
        "model": model,
        "input": [
            {"role": "developer", "content": instructions},
            {"role": "user", "content": evidence},
        ],
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": _REASONING_EFFORT},
        "text": {
            "verbosity": _TEXT_VERBOSITY,
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": response_schema,
            },
        },
        "truncation": "disabled",
        "store": False,
    }
    if service_tier is not None:
        arguments["service_tier"] = service_tier
    response = OpenAI(
        api_key=api_key,
        timeout=_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ).responses.create(**arguments)
    status = getattr(response, "status", None)
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown"
        raise RuntimeError(f"OpenAI returned an incomplete response: {reason}")
    if status not in {None, "completed"}:
        raise RuntimeError(f"OpenAI structured response failed with status {status}")
    text = response.output_text or ""
    if not text:
        raise RuntimeError("OpenAI returned an empty structured response")
    effective_model = getattr(response, "model", None)
    response_id = getattr(response, "id", None)
    if type(effective_model) is not str or not effective_model.strip():
        raise RuntimeError("OpenAI response has no effective model")
    if type(response_id) is not str or not response_id.strip():
        raise RuntimeError("OpenAI response has no response ID")
    usage = _jsonable(getattr(response, "usage", None))
    return StructuredProviderOutput(
        response_text=text,
        cost=_cost_from_usage(usage, model=model, service_tier=service_tier),
        generation={
            "provider": "openai",
            "requested_model": model,
            "effective_model": effective_model,
            "response_id": response_id,
            "request_parameters": {
                key: value for key, value in arguments.items()
                if key not in {"input", "model"}
            },
            "usage": usage,
        },
    )


def _cost_from_usage(
    usage: object,
    *,
    model: str,
    service_tier: str | None,
) -> dict[str, float | str | None]:
    if not isinstance(usage, dict):
        return RunCost().fields()
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    details = usage.get("input_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else 0
    return RunCost.from_event(
        {"usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached or 0,
        }},
        model=model,
        service_tier=service_tier,
    ).fields()


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    return str(value)
