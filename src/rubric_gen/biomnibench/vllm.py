"""Strict vLLM endpoint specifications shared by workflow commands."""

from __future__ import annotations

import argparse
from urllib.parse import urlparse


def add_vllm_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vllm",
        action="append",
        default=[],
        metavar="URL::MODEL",
        help=(
            "Route MODEL to a vLLM OpenAI-compatible server at URL. Repeat for "
            "multiple models."
        ),
    )


def normalize_vllm_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"invalid vLLM base URL: {value!r}")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("vLLM base URLs must not contain params, queries, or fragments")
    return normalized if normalized.endswith("/v1") else normalized + "/v1"


def parse_vllm_endpoints(values: list[str] | tuple[str, ...]) -> dict[str, str]:
    endpoints: dict[str, str] = {}
    for specification in values:
        if "::" not in specification:
            raise ValueError("--vllm must use URL::MODEL")
        url, model = specification.rsplit("::", 1)
        model = model.strip()
        if not model:
            raise ValueError(f"invalid --vllm specification: {specification!r}")
        if model in endpoints:
            raise ValueError(f"duplicate vLLM model: {model}")
        endpoints[model] = normalize_vllm_base_url(url)
    return endpoints
