"""Define behavior-detection configuration and prepared jobs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rubric_gen.detection.config import (
    DEFAULT_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_MAX_EVENT_TEXT_CHARS,
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    JUDGE_MAX_ATTEMPTS,
)
from rubric_gen.detection.sources import AuditCase, AuditSource
from rubric_gen.detection.targets import detection_target
from rubric_gen.runtime.llm import StructuredRequest


@dataclass(frozen=True)
class DetectionConfig:
    source: AuditSource
    models: tuple[str, ...]
    output_dir: Path
    max_concurrency: int = 3
    resume: bool = False
    detection: str = "rh"
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    max_event_text_chars: int = DEFAULT_MAX_EVENT_TEXT_CHARS
    max_command_output_chars: int = DEFAULT_MAX_COMMAND_OUTPUT_CHARS
    primary_rule: str = "any_detect"

    def __post_init__(self) -> None:
        detection_target(self.detection)
        if (
            not self.models
            or len(set(self.models)) != len(self.models)
            or any(type(model) is not str or not model.strip() for model in self.models)
        ):
            raise ValueError("judge models must be unique non-empty strings")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")
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
        if self.primary_rule not in {"majority", "any_detect", "unanimous_detects"}:
            raise ValueError("primary_rule is invalid")


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

    def record(self) -> dict[str, object]:
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
            "max_attempts": JUDGE_MAX_ATTEMPTS,
        }


@dataclass(frozen=True)
class PreparedPanel:
    jobs: tuple[PreparedJob, ...]
    failures: tuple[PreparationFailure, ...]
