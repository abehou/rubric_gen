"""Reported and estimated terminal-agent run costs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GEMINI_API_PRICING_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
GEMINI_COST_SOURCE = "estimated_google_gemini_api_standard"
GEMINI_STANDARD_PRICES_PER_MILLION = {
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00, "cached": 0.15},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50, "cached": 0.025},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00, "cached": 0.05},
    "gemini-3-flash": {"input": 0.50, "output": 3.00, "cached": 0.05},
}


@dataclass(frozen=True)
class RunCost:
    cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    source: str | None = None

    @classmethod
    def from_stream(cls, stream_path: Path) -> "RunCost":
        cost_usd: float | None = None
        estimated_cost_usd: float | None = None
        if not stream_path.is_file():
            return cls()
        with stream_path.open() as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_cost = cls.from_event(event)
                if event_cost.cost_usd is not None:
                    cost_usd = event_cost.cost_usd
                if event_cost.estimated_cost_usd is not None:
                    estimated_cost_usd = event_cost.estimated_cost_usd
        source = "reported" if cost_usd is not None else None
        if source is None and estimated_cost_usd is not None:
            source = GEMINI_COST_SOURCE
        return cls(cost_usd, estimated_cost_usd, source)

    @classmethod
    def from_status(cls, status_path: Path) -> "RunCost":
        if not status_path.is_file():
            return cls()
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return cls()
        cost_usd = _parse_cost_value(status.get("cost_usd"))
        estimated_cost_usd = _parse_cost_value(status.get("estimated_cost_usd"))
        return cls(cost_usd, estimated_cost_usd, status.get("cost_source"))

    @classmethod
    def for_run_dir(cls, run_dir: Path) -> "RunCost":
        status_cost = cls.from_status(run_dir / "status.json")
        if status_cost.cost_usd is not None or status_cost.estimated_cost_usd is not None:
            return status_cost
        return cls.from_stream(run_dir / "trajectory.stream.jsonl")

    @classmethod
    def from_event(cls, event: Any) -> "RunCost":
        cost_usd = _find_cost_usd(event)
        estimated_cost_usd = _estimate_gemini_event_cost(event)
        source = "reported" if cost_usd is not None else None
        if source is None and estimated_cost_usd is not None:
            source = GEMINI_COST_SOURCE
        return cls(cost_usd, estimated_cost_usd, source)

    def fields(self) -> dict[str, float | str | None]:
        return {
            "cost_usd": self.cost_usd,
            "estimated_cost_usd": self.estimated_cost_usd,
            "cost_source": self.source,
        }


def _find_cost_usd(value: Any) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_usd_cost_key(key):
                cost = _parse_cost_value(child)
                if cost is not None:
                    return cost
            cost = _find_cost_usd(child)
            if cost is not None:
                return cost
    elif isinstance(value, list):
        for child in value:
            cost = _find_cost_usd(child)
            if cost is not None:
                return cost
    return None


def _is_usd_cost_key(key: str) -> bool:
    normalized = "".join(char for char in key.lower() if char.isalnum())
    return "cost" in normalized and "usd" in normalized


def _parse_cost_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().removeprefix("$"))
        except ValueError:
            return None
    return None


def _estimate_gemini_event_cost(event: Any) -> float | None:
    if not isinstance(event, dict):
        return None
    stats = event.get("stats")
    models = stats.get("models") if isinstance(stats, dict) else None
    if not isinstance(models, dict):
        return None

    total = 0.0
    matched = False
    for model_name, model_stats in models.items():
        if not isinstance(model_name, str) or not isinstance(model_stats, dict):
            continue
        prices = GEMINI_STANDARD_PRICES_PER_MILLION.get(model_name)
        if prices is None:
            continue
        matched = True
        cached_tokens = _parse_token_count(model_stats.get("cached")) or 0
        input_tokens = _parse_token_count(model_stats.get("input"))
        if input_tokens is None:
            total_input = _parse_token_count(model_stats.get("input_tokens")) or 0
            input_tokens = max(total_input - cached_tokens, 0)
        output_tokens = _parse_token_count(model_stats.get("output_tokens")) or 0
        total += (
            input_tokens * prices["input"]
            + cached_tokens * prices["cached"]
            + output_tokens * prices["output"]
        ) / 1_000_000
    return round(total, 6) if matched else None


def _parse_token_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
