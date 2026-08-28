"""Calculate reward-hacking request usage and cost."""

from __future__ import annotations

from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    estimate_input_tokens,
)
from rubric_gen.runtime.pricing import (
    ANTHROPIC_PRICES_PER_MILLION,
    GEMINI_PRICES_PER_MILLION,
    HOSTED_PRICES_PER_MILLION,
    OPENAI_LONG_CONTEXT_THRESHOLD,
    OPENAI_LONG_INPUT_MULTIPLIER,
    OPENAI_LONG_OUTPUT_MULTIPLIER,
    OPENAI_PRICES_PER_MILLION,
)


def cache_write_reservation_tokens(
    model: str,
    request: StructuredRequest,
    input_tokens: int,
) -> int:
    """Reserve cache-write pricing only for the stable prompt prefix."""

    if model not in {
        *OPENAI_PRICES_PER_MILLION,
        *ANTHROPIC_PRICES_PER_MILLION,
    }:
        return 0
    prefix_only = StructuredRequest(
        instructions=request.instructions,
        evidence="",
        schema_name=request.schema_name,
        schema=request.schema,
        max_output_tokens=request.max_output_tokens,
        prompt_layout=request.prompt_layout,
    )
    return min(estimate_input_tokens(model, prefix_only), input_tokens)


def request_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cached_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
) -> float | None:
    price = HOSTED_PRICES_PER_MILLION.get(model)
    if price is None:
        return None
    if min(
        input_tokens,
        output_tokens,
        cached_input_tokens,
        cache_write_input_tokens,
    ) < 0:
        raise ValueError("usage tokens must not be negative")
    if cached_input_tokens + cache_write_input_tokens > input_tokens:
        raise ValueError("cached and cache-write tokens exceed total input")
    uncached = input_tokens - cached_input_tokens - cache_write_input_tokens
    input_price = price["input"]
    cached_price = price.get("cached", input_price)
    output_price = price["output"]
    if (
        model in GEMINI_PRICES_PER_MILLION
        and "long_threshold" in price
        and input_tokens > int(price["long_threshold"])
    ):
        input_price = price["long_input"]
        cached_price = price["long_cached"]
        output_price = price["long_output"]
    cache_write_price = price.get("cache_write", input_price)
    if (
        model in OPENAI_PRICES_PER_MILLION
        and input_tokens > OPENAI_LONG_CONTEXT_THRESHOLD
    ):
        input_price *= OPENAI_LONG_INPUT_MULTIPLIER
        cached_price *= OPENAI_LONG_INPUT_MULTIPLIER
        cache_write_price *= OPENAI_LONG_INPUT_MULTIPLIER
        output_price *= OPENAI_LONG_OUTPUT_MULTIPLIER
    return (
        uncached * input_price
        + cached_input_tokens * cached_price
        + cache_write_input_tokens * cache_write_price
        + output_tokens * output_price
    ) / 1_000_000


def usage_tokens(generation: GenerationResult) -> dict[str, int] | None:
    usage = generation.provider_metadata.get("usage")
    if not isinstance(usage, dict):
        return None
    input_value = usage.get("input_tokens", usage.get("promptTokenCount"))
    output_value = usage.get("output_tokens", usage.get("candidatesTokenCount"))
    if type(input_value) is not int or type(output_value) is not int:
        return None
    cached = 0
    cache_write = 0
    details = usage.get("input_tokens_details")
    if isinstance(details, dict):
        cached_value = details.get("cached_tokens", 0)
        write_value = details.get(
            "cache_write_tokens", details.get("cache_creation_tokens", 0)
        )
        cached = cached_value if type(cached_value) is int else 0
        cache_write = write_value if type(write_value) is int else 0
    if generation.provider == "anthropic":
        cached_value = usage.get("cache_read_input_tokens", 0)
        write_value = usage.get("cache_creation_input_tokens", 0)
        cached = cached_value if type(cached_value) is int else 0
        cache_write = write_value if type(write_value) is int else 0
        input_value += cached + cache_write
    elif generation.provider == "google":
        cached_value = usage.get("cachedContentTokenCount", 0)
        thoughts_value = usage.get("thoughtsTokenCount", 0)
        cached = cached_value if type(cached_value) is int else 0
        output_value += thoughts_value if type(thoughts_value) is int else 0
    if min(input_value, output_value, cached, cache_write) < 0:
        return None
    if cached + cache_write > input_value:
        return None
    return {
        "input_tokens": input_value,
        "output_tokens": output_value,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": cache_write,
    }
