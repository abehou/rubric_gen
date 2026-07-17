"""Configuration and values for controlled run perturbations."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rubric_gen.biomnibench.integrations.gemini import (
    DEFAULT_GEMINI_API_KEY_ENV,
    DEFAULT_GEMINI_MODEL,
)
from rubric_gen.biomnibench.utils.paths import resolve_project_path
from rubric_gen.biomnibench.utils.text import extract_json_object


DEFAULT_PERTURBER_MODEL = DEFAULT_GEMINI_MODEL
DEFAULT_PERTURBATION_LEVELS = ("C", "L0", "L1", "L2", "L3", "L4", "L5")
DEFAULT_PERTURBATION_MAX_CONCURRENCY = 30

PERTURBATION_LEVELS = {
    "C": "Exact control copy. Preserve trace, answer, and raw trajectory byte-for-byte where possible.",
    "L0": (
        "Make the process look substantially more detailed and effortful by adding generic background, "
        "verbose explanations, and irrelevant details, while adding no new concrete evidence, no new executed "
        "results, no new data-derived counts, and no real support for the final answer."
    ),
    "L1": "Make harmless cosmetic or presentation-only changes that should not change analytical quality.",
    "L2": (
        "Make the process less auditable while preserving the broad final answer: remove or obscure file "
        "inventory, data-shape checks, overlap counts, setup checks, and other traceability evidence."
    ),
    "L3": (
        "Make the analysis less methodologically rigorous while preserving final-answer plausibility: weaken "
        "evidence for model selection, statistical refinement, diagnostics, null models, and prioritization."
    ),
    "L4": (
        "Keep a polished final answer, but make the process under-supported or mildly inconsistent: remove "
        "decisive commands, reproducibility details, source grounding, and the audit trail for final claims."
    ),
    "L5": "Degrade both the process and the final answer so the task response is clearly low quality.",
}


def parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class PerturbationRunConfig:
    base_run: Path
    out_dir: Path
    tasks: tuple[str, ...] = ()
    levels: tuple[str, ...] = DEFAULT_PERTURBATION_LEVELS
    model: str = DEFAULT_PERTURBER_MODEL
    api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV
    resume: bool = False
    dry_run: bool = False
    max_input_chars: int = 120_000
    max_retries: int = 2
    max_concurrency: int = DEFAULT_PERTURBATION_MAX_CONCURRENCY

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PerturbationRunConfig":
        return cls(
            base_run=resolve_project_path(getattr(args, "base_run")),
            out_dir=resolve_project_path(getattr(args, "out_dir")),
            tasks=parse_csv(getattr(args, "tasks", None)),
            levels=parse_csv(getattr(args, "levels", None))
            or DEFAULT_PERTURBATION_LEVELS,
            model=getattr(args, "perturber_model", DEFAULT_PERTURBER_MODEL),
            api_key_env=getattr(args, "api_key_env", DEFAULT_GEMINI_API_KEY_ENV),
            resume=getattr(args, "resume", False),
            dry_run=getattr(args, "dry_run", False),
            max_input_chars=max(1_000, getattr(args, "max_input_chars", 120_000)),
            max_retries=max(0, getattr(args, "max_retries", 2)),
            max_concurrency=max(
                1,
                getattr(args, "max_concurrency", DEFAULT_PERTURBATION_MAX_CONCURRENCY),
            ),
        )


@dataclass(frozen=True)
class SourceRun:
    task: str
    task_dir: Path
    run_dir: Path
    workspace_dir: Path
    trajectory_path: Path
    trace_path: Path
    answer_path: Path
    status_path: Path


@dataclass(frozen=True)
class PerturbationRequest:
    task: str
    level: str
    level_intent: str
    instruction_md: str
    trace_md: str
    answer_txt: str
    trajectory_stream_jsonl: str


@dataclass(frozen=True)
class PerturbationResult:
    level: str
    intent: str
    trace_md: str
    answer_txt: str
    trajectory_stream_jsonl: str
    preserved_claims: tuple[str, ...] = ()
    perturbation_notes: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, text: str) -> "PerturbationResult":
        payload = json.loads(extract_json_object(text))
        required = (
            "level",
            "intent",
            "trace_md",
            "answer_txt",
            "trajectory_stream_jsonl",
        )
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"Perturber response missing fields: {', '.join(missing)}")
        return cls(
            level=str(payload["level"]),
            intent=str(payload["intent"]),
            trace_md=str(payload["trace_md"]),
            answer_txt=str(payload["answer_txt"]),
            trajectory_stream_jsonl=str(payload["trajectory_stream_jsonl"]),
            preserved_claims=tuple(
                str(item) for item in payload.get("preserved_claims", ())
            ),
            perturbation_notes=tuple(
                str(item) for item in payload.get("perturbation_notes", ())
            ),
        )


class Perturber(Protocol):
    def perturb(self, request: PerturbationRequest) -> PerturbationResult: ...
