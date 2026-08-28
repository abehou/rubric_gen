"""Define reward-hacking panel configuration and prepared jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rubric_gen.reward_hacking.protocol import (
    DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_RH_MAX_EVENT_TEXT_CHARS,
    DEFAULT_RH_MAX_INPUT_TOKENS,
    DEFAULT_RH_MAX_OUTPUT_TOKENS,
)
from rubric_gen.reward_hacking.sources import AuditCase, AuditSource
from rubric_gen.reward_hacking.targets import detection_target
from rubric_gen.runtime.llm import StructuredRequest
from rubric_gen.runtime.pricing import OPENAI_PRICES_PER_MILLION


DEFAULT_PANEL_MAX_COST_USD = 50.0


@dataclass(frozen=True)
class RewardHackingJudgeConfig:
    source: AuditSource
    models: tuple[str, ...]
    output_dir: Path
    max_concurrency: int = 3
    max_retries: int = 1
    resume: bool = False
    base_urls: dict[str, str] = field(default_factory=dict)
    detection: str = "rh"
    max_input_tokens: int = DEFAULT_RH_MAX_INPUT_TOKENS
    max_output_tokens: int = DEFAULT_RH_MAX_OUTPUT_TOKENS
    max_event_text_chars: int = DEFAULT_RH_MAX_EVENT_TEXT_CHARS
    max_command_output_chars: int = DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS
    max_cost_usd: float | None = DEFAULT_PANEL_MAX_COST_USD
    execution: str = "standard"
    primary_rule: str = "any_detect"

    def __post_init__(self) -> None:
        detection_target(self.detection)
        if (
            not self.models
            or len(set(self.models)) != len(self.models)
            or any(type(model) is not str or not model.strip() for model in self.models)
        ):
            raise ValueError("judge models must be unique non-empty strings")
        if not set(self.base_urls) <= set(self.models):
            raise ValueError("vLLM endpoints must match selected judge models")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if not 10_000 <= self.max_input_tokens <= 272_000:
            raise ValueError("max_input_tokens must be between 10000 and 272000")
        if not 1_024 <= self.max_output_tokens <= 16_384:
            raise ValueError("max_output_tokens must be between 1024 and 16384")
        if not 4_096 <= self.max_event_text_chars <= 262_144:
            raise ValueError(
                "max_event_text_chars must be between 4096 and 262144"
            )
        if not 512 <= self.max_command_output_chars <= self.max_event_text_chars:
            raise ValueError(
                "max_command_output_chars must be between 512 and "
                "max_event_text_chars"
            )
        if self.max_cost_usd is not None and self.max_cost_usd <= 0:
            raise ValueError("max_cost_usd must be positive")
        if self.execution not in {"standard", "batch"}:
            raise ValueError("execution must be standard or batch")
        if self.primary_rule not in {"majority", "any_detect", "unanimous_detects"}:
            raise ValueError("primary_rule is invalid")
        if self.execution == "batch" and (
            len(self.models) != 1
            or self.models[0] not in OPENAI_PRICES_PER_MILLION
            or self.base_urls
        ):
            raise ValueError("batch execution requires exactly one hosted OpenAI model")


@dataclass(frozen=True)
class PreparedJob:
    case: AuditCase
    model: str
    requests: tuple[StructuredRequest, ...]
    input_tokens: tuple[int, ...]
    compact_stats: dict[str, object]
    aggregation: str

    @property
    def source_kind(self) -> str:
        return self.case.source_kind

    @property
    def chunked(self) -> bool:
        return len(self.requests) > 1

    @property
    def requires_synthesis(self) -> bool:
        return self.aggregation == "synthesis" and self.chunked

    @property
    def request_stage(self) -> str:
        return "chunk" if self.chunked or self.aggregation == "max_score" else "direct"


@dataclass(frozen=True)
class PreparationFailure:
    case: AuditCase
    model: str
    error_type: str
    error: str

    def record(self, max_retries: int) -> dict[str, object]:
        return {
            "case_id": self.case.case_id,
            "source_kind": self.case.source_kind,
            "source_path": str(self.case.path),
            "provider": self.model,
            "model": self.model,
            "status": "failed",
            "error_type": self.error_type,
            "error": self.error,
            "attempt_count": 0,
            "max_retries": max_retries,
            "retry_exhausted": False,
        }


@dataclass(frozen=True)
class PreparedPanel:
    jobs: tuple[PreparedJob, ...]
    failures: tuple[PreparationFailure, ...]
