"""Strict AutoRubric execution for one sealed submission artifact."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rubric_gen.submission_revision.autorubric import (
    AUTORUBRIC_CODE_IDENTITY,
    HARDENED_MULTI_CHOICE_SYSTEM_PROMPT,
    AuthoritativeRubric,
    ConvertedAutoRubricReport,
    build_autorubric,
    convert_ensemble_report,
    parse_autorubric_rubric,
)
from rubric_gen.submission_revision.rubrics.schema import canonical_json


AUTORUBRIC_REQUEST_TIMEOUT_SECONDS = 300.0
AUTORUBRIC_MAX_OUTPUT_TOKENS = 512
AUTORUBRIC_PROVIDER_PARALLELISM = 8
AUTORUBRIC_MAX_CRITERIA_PER_RUBRIC = 32
AUTORUBRIC_MAX_PROMPT_BYTES_PER_CALL = 500_000
AUTORUBRIC_MAX_PROMPT_BYTES_PER_RUBRIC = 4_000_000
AUTORUBRIC_MAX_BANK_CRITERION_CALLS = 128
AUTORUBRIC_MAX_BANK_PROMPT_BYTES = 16_000_000
AUTORUBRIC_MAX_BANK_OUTPUT_TOKENS = (
    AUTORUBRIC_MAX_BANK_CRITERION_CALLS * AUTORUBRIC_MAX_OUTPUT_TOKENS
)


@dataclass(frozen=True)
class AutoRubricCostShape:
    """Exact text size and call count for one criterion-grading rubric."""

    criterion_calls: int
    artifact_characters: int
    artifact_bytes: int
    largest_prompt_bytes: int
    total_prompt_bytes: int
    total_output_tokens: int

    def as_json(self) -> dict[str, int]:
        return {
            "criterion_calls": self.criterion_calls,
            "artifact_characters": self.artifact_characters,
            "artifact_bytes": self.artifact_bytes,
            "largest_prompt_bytes": self.largest_prompt_bytes,
            "total_prompt_bytes": self.total_prompt_bytes,
            "total_output_tokens": self.total_output_tokens,
        }

    @classmethod
    def from_json(cls, value: object) -> "AutoRubricCostShape":
        if type(value) is not dict or set(value) != {
            "criterion_calls",
            "artifact_characters",
            "artifact_bytes",
            "largest_prompt_bytes",
            "total_prompt_bytes",
            "total_output_tokens",
        }:
            raise ValueError("AutoRubric cost shape is not exact")
        if any(type(item) is not int or item < 1 for item in value.values()):
            raise ValueError("AutoRubric cost shape values must be positive integers")
        return cls(**value)


def _criterion_prompt_text(
    criterion: object,
    artifact_payload: str,
) -> str:
    requirement = getattr(criterion, "requirement")
    levels = getattr(criterion, "levels")
    options = "\n".join(
        f"{index}. {level.display_label}"
        for index, level in enumerate(levels, start=1)
    )
    return (
        f"<question>\n{requirement}\n</question>\n\n"
        f"<options>\n{options}\n</options>\n\n"
        f"<submission>\n{artifact_payload}\n</submission>"
    )


def autorubric_cost_shape(
    rubric: AuthoritativeRubric,
    *,
    review_text: str,
    answer_text: str,
) -> AutoRubricCostShape:
    """Return the pure exact prompt-text shape. This function makes no calls."""

    payload = submission_payload(review_text, answer_text)
    prompt_bytes = [
        len(HARDENED_MULTI_CHOICE_SYSTEM_PROMPT.encode("utf-8"))
        + len(_criterion_prompt_text(criterion, payload).encode("utf-8"))
        for criterion in rubric.criteria
    ]
    return AutoRubricCostShape(
        criterion_calls=len(rubric.criteria),
        artifact_characters=len(payload),
        artifact_bytes=len(payload.encode("utf-8")),
        largest_prompt_bytes=max(prompt_bytes),
        total_prompt_bytes=sum(prompt_bytes),
        total_output_tokens=len(rubric.criteria) * AUTORUBRIC_MAX_OUTPUT_TOKENS,
    )


def validate_autorubric_cost_shape(shape: AutoRubricCostShape) -> None:
    """Reject one rubric before any criterion call crosses the provider boundary."""

    if shape.total_output_tokens != (
        shape.criterion_calls * AUTORUBRIC_MAX_OUTPUT_TOKENS
    ):
        raise ValueError("AutoRubric output token budget is not exact")
    if shape.criterion_calls > AUTORUBRIC_MAX_CRITERIA_PER_RUBRIC:
        raise ValueError(
            f"AutoRubric requires {shape.criterion_calls} calls; the per-rubric "
            f"limit is {AUTORUBRIC_MAX_CRITERIA_PER_RUBRIC}"
        )
    if shape.largest_prompt_bytes > AUTORUBRIC_MAX_PROMPT_BYTES_PER_CALL:
        raise ValueError(
            f"AutoRubric largest prompt is {shape.largest_prompt_bytes} bytes; the "
            f"per-call limit is {AUTORUBRIC_MAX_PROMPT_BYTES_PER_CALL}"
        )
    if shape.total_prompt_bytes > AUTORUBRIC_MAX_PROMPT_BYTES_PER_RUBRIC:
        raise ValueError(
            f"AutoRubric prompts total {shape.total_prompt_bytes} bytes; the "
            f"per-rubric limit is {AUTORUBRIC_MAX_PROMPT_BYTES_PER_RUBRIC}"
        )


def preflight_autorubric_bank(
    rubric_texts: Sequence[str],
    *,
    review_text: str,
    answer_text: str,
) -> dict[str, object]:
    """Atomically validate a complete bank's cost shape without network access."""

    if isinstance(rubric_texts, (str, bytes, bytearray)) or not rubric_texts:
        raise ValueError("AutoRubric bank must contain at least one rubric text")
    member_shapes = []
    for rubric_text in rubric_texts:
        parsed = parse_autorubric_rubric(rubric_text)
        shape = autorubric_cost_shape(
            parsed,
            review_text=review_text,
            answer_text=answer_text,
        )
        validate_autorubric_cost_shape(shape)
        member_shapes.append(shape)
    total_calls = sum(shape.criterion_calls for shape in member_shapes)
    total_prompt_bytes = sum(shape.total_prompt_bytes for shape in member_shapes)
    total_output_tokens = sum(shape.total_output_tokens for shape in member_shapes)
    if total_calls > AUTORUBRIC_MAX_BANK_CRITERION_CALLS:
        raise ValueError(
            f"AutoRubric bank requires {total_calls} calls; the bank limit is "
            f"{AUTORUBRIC_MAX_BANK_CRITERION_CALLS}"
        )
    if total_prompt_bytes > AUTORUBRIC_MAX_BANK_PROMPT_BYTES:
        raise ValueError(
            f"AutoRubric bank prompts total {total_prompt_bytes} bytes; the bank "
            f"limit is {AUTORUBRIC_MAX_BANK_PROMPT_BYTES}"
        )
    if total_output_tokens > AUTORUBRIC_MAX_BANK_OUTPUT_TOKENS:
        raise ValueError(
            f"AutoRubric bank output budget is {total_output_tokens} tokens; the "
            f"limit is {AUTORUBRIC_MAX_BANK_OUTPUT_TOKENS}"
        )
    return {
        "members": [shape.as_json() for shape in member_shapes],
        "member_count": len(member_shapes),
        "criterion_calls": total_calls,
        "total_prompt_bytes": total_prompt_bytes,
        "total_output_tokens": total_output_tokens,
        "limits": {
            "max_bank_criterion_calls": AUTORUBRIC_MAX_BANK_CRITERION_CALLS,
            "max_bank_prompt_bytes": AUTORUBRIC_MAX_BANK_PROMPT_BYTES,
            "max_bank_output_tokens": AUTORUBRIC_MAX_BANK_OUTPUT_TOKENS,
            "max_criteria_per_rubric": AUTORUBRIC_MAX_CRITERIA_PER_RUBRIC,
            "max_prompt_bytes_per_call": AUTORUBRIC_MAX_PROMPT_BYTES_PER_CALL,
            "max_prompt_bytes_per_rubric": AUTORUBRIC_MAX_PROMPT_BYTES_PER_RUBRIC,
        },
    }


@dataclass(frozen=True)
class AutoRubricRunSpec:
    """The complete non-secret execution contract for one grading attempt."""

    requested_model: str
    litellm_model: str
    provider: str
    api_base: str | None
    option_shuffle_seed: int
    criterion_count: int
    criterion_parallelism: int
    temperature: float
    reasoning_effort: str | None
    cost_shape: AutoRubricCostShape

    def as_json(self) -> dict[str, object]:
        return {
            "requested_model": self.requested_model,
            "litellm_model": self.litellm_model,
            "provider": self.provider,
            "api_base": self.api_base,
            "autorubric_release": AUTORUBRIC_CODE_IDENTITY["release"],
            "option_shuffle_seed": self.option_shuffle_seed,
            "llm_seed": None,
            "criterion_count": self.criterion_count,
            "criterion_parallelism": self.criterion_parallelism,
            "temperature": self.temperature,
            "reasoning_effort": self.reasoning_effort,
            "cost_shape": self.cost_shape.as_json(),
            "max_output_tokens": AUTORUBRIC_MAX_OUTPUT_TOKENS,
            "request_timeout_seconds": AUTORUBRIC_REQUEST_TIMEOUT_SECONDS,
            "provider_retries": 0,
            "provider_storage": False if self.provider == "openai" else None,
            "repository_result_cache": False,
            "prompt_cache_control": "default",
            "shuffle_options": True,
            "auto_na_option": False,
            "ordinal_aggregation": "mean",
            "normalize_autorubric_score": True,
            "authoritative_score": "repository-signed-points",
            "autorubric_aggregate_role": (
                "diagnostic-only: normalized options discard absolute and signed "
                "repository point magnitudes"
            ),
            "system_prompt_sha256": hashlib.sha256(
                HARDENED_MULTI_CHOICE_SYSTEM_PROMPT.encode("utf-8")
            ).hexdigest(),
        }


@dataclass(frozen=True)
class AutoRubricArtifactRecords:
    """The three judge artifacts written for one successful attempt."""

    reward: dict[str, int]
    evaluation: dict[str, object]
    usage: dict[str, object]


def provider_and_litellm_model(
    requested_model: str,
    *,
    api_base: str | None,
) -> tuple[str, str]:
    """Map the repository model name to one explicit LiteLLM provider route."""

    if type(requested_model) is not str or not requested_model.strip():
        raise ValueError("judge model must be a non-empty string")
    if api_base is not None:
        if type(api_base) is not str or not api_base.strip():
            raise ValueError("judge API base must be a non-empty URL")
        return "vllm", f"openai/{requested_model}"
    if "/" in requested_model:
        raise ValueError(
            "judge model must use the repository's unqualified model-name form"
        )
    if requested_model.startswith("gemini"):
        return "google", f"gemini/{requested_model}"
    if requested_model.startswith("claude"):
        return "anthropic", f"anthropic/{requested_model}"
    if requested_model.startswith(("gpt-5", "o1", "o3", "o4")):
        return "openai", f"openai/responses/{requested_model}"
    if requested_model.startswith(("gpt-", "chatgpt-")):
        return "openai", f"openai/{requested_model}"
    raise ValueError(
        f"cannot infer judge provider from model {requested_model!r}; expected a "
        "Gemini, Claude, GPT, or o-series model, or an explicit API base"
    )


def deterministic_grading_seed(
    *,
    rubric_sha256: str,
    review_sha256: str,
    answer_sha256: str,
    requested_model: str,
    api_base: str | None,
    benchmark: str,
    assignment_identity: str,
    grading_engine: str,
    engine_release: str,
    repeat_index: int,
) -> int:
    """Derive one stable seed from all content and execution identities."""

    material = canonical_json(
        {
            "rubric_sha256": rubric_sha256,
            "review_sha256": review_sha256,
            "answer_sha256": answer_sha256,
            "requested_model": requested_model,
            "api_base": api_base,
            "benchmark": benchmark,
            "assignment_identity": assignment_identity,
            "grading_engine": grading_engine,
            "engine_release": engine_release,
            "repeat_index": repeat_index,
        }
    )
    return int.from_bytes(
        hashlib.sha256(material.encode("utf-8")).digest()[:4],
        byteorder="big",
        signed=False,
    ) & 0x7FFF_FFFF


def submission_payload(review_text: str, answer_text: str) -> str:
    """Encode harness-selected evidence without adding executable delimiters."""

    if type(review_text) is not str or type(answer_text) is not str:
        raise TypeError("judge evidence must be text")
    return json.dumps(
        {
            "review_artifact": review_text,
            "final_answer": answer_text if answer_text else None,
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
    )


def build_run_spec(
    rubric: AuthoritativeRubric,
    *,
    requested_model: str,
    api_base: str | None,
    seed: int,
    criterion_parallelism: int,
    cost_shape: AutoRubricCostShape,
) -> AutoRubricRunSpec:
    """Validate and construct the execution contract."""

    if type(seed) is not int or isinstance(seed, bool) or not 0 <= seed < 2**31:
        raise ValueError("AutoRubric seed must be a non-negative 31-bit integer")
    if (
        type(criterion_parallelism) is not int
        or isinstance(criterion_parallelism, bool)
        or criterion_parallelism < 1
    ):
        raise ValueError("AutoRubric criterion parallelism must be positive")
    provider, litellm_model = provider_and_litellm_model(
        requested_model,
        api_base=api_base,
    )
    if cost_shape.criterion_calls != len(rubric.criteria):
        raise ValueError("AutoRubric cost shape criterion count changed")
    validate_autorubric_cost_shape(cost_shape)
    if provider == "openai" and requested_model.startswith("gpt-5.6"):
        temperature = 0.0
        reasoning_effort = "none"
    elif provider == "openai" and litellm_model.startswith("openai/responses/"):
        raise ValueError(
            "the AutoRubric engine supports only GPT-5.6 on OpenAI Responses; "
            "other reasoning models can reject AutoRubric's mandatory temperature"
        )
    else:
        temperature = 0.0
        reasoning_effort = None
    return AutoRubricRunSpec(
        requested_model=requested_model,
        litellm_model=litellm_model,
        provider=provider,
        api_base=api_base,
        option_shuffle_seed=seed,
        criterion_count=len(rubric.criteria),
        criterion_parallelism=criterion_parallelism,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        cost_shape=cost_shape,
    )


def artifact_records(
    converted: ConvertedAutoRubricReport,
    spec: AutoRubricRunSpec,
) -> AutoRubricArtifactRecords:
    """Build lossless artifacts from one validated AutoRubric report."""

    execution = spec.as_json()
    evaluation = {
        **converted.evaluation,
        "autorubric": {
            "code_identity": dict(AUTORUBRIC_CODE_IDENTITY),
            "execution": execution,
            "agreement": converted.agreement,
            "completion_cost": converted.completion_cost,
            "raw_report": converted.raw_report,
        },
    }
    usage = {
        "code_identity": dict(AUTORUBRIC_CODE_IDENTITY),
        "execution": execution,
        "token_usage": converted.usage,
        "completion_cost": converted.completion_cost,
    }
    return AutoRubricArtifactRecords(
        reward=dict(converted.reward),
        evaluation=evaluation,
        usage=usage,
    )


def records_from_raw_report(
    rubric: AuthoritativeRubric,
    raw_report: object,
    spec: AutoRubricRunSpec,
) -> tuple[ConvertedAutoRubricReport, AutoRubricArtifactRecords]:
    """Validate a report and construct all authoritative output records."""

    converted = convert_ensemble_report(rubric, raw_report)
    return converted, artifact_records(converted, spec)


async def grade_submission(
    *,
    rubric_text: str,
    review_text: str,
    answer_text: str,
    requested_model: str,
    api_base: str | None,
    seed: int,
    criterion_parallelism: int,
) -> AutoRubricArtifactRecords:
    """Grade one artifact without AutoRubric caching or checkpoint machinery."""

    parsed = parse_autorubric_rubric(rubric_text)
    cost_shape = autorubric_cost_shape(
        parsed,
        review_text=review_text,
        answer_text=answer_text,
    )
    spec = build_run_spec(
        parsed,
        requested_model=requested_model,
        api_base=api_base,
        seed=seed,
        criterion_parallelism=criterion_parallelism,
        cost_shape=cost_shape,
    )
    # Do not import the provider stack until the complete pre-dispatch contract passes.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    from autorubric import LLMConfig
    from autorubric.graders import CriterionGrader

    api_key = None
    if spec.provider == "vllm":
        api_key = os.getenv("VLLM_API_KEY", "EMPTY")
    llm_config = LLMConfig(
        model=spec.litellm_model,
        temperature=spec.temperature,
        max_tokens=AUTORUBRIC_MAX_OUTPUT_TOKENS,
        timeout=AUTORUBRIC_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
        max_parallel_requests=spec.criterion_parallelism,
        cache_enabled=False,
        api_key=api_key,
        api_base=spec.api_base,
        thinking=spec.reasoning_effort,
        prompt_caching=False,
        extra_params={
            "num_retries": 0,
            **({"store": False} if spec.provider == "openai" else {}),
        },
    )
    grader = CriterionGrader(
        llm_config=llm_config,
        ordinal_aggregation="mean",
        multi_choice_system_prompt=HARDENED_MULTI_CHOICE_SYSTEM_PROMPT,
        normalize=True,
        shuffle_options=True,
        auto_na_option=False,
        seed=spec.option_shuffle_seed,
    )
    autorubric = build_autorubric(parsed)
    report = await autorubric.grade(
        to_grade=submission_payload(review_text, answer_text),
        grader=grader,
    )
    _converted, records = records_from_raw_report(parsed, report, spec)
    return records


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--answer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-base")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--criterion-parallelism", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = asyncio.run(
        grade_submission(
            rubric_text=args.rubric.read_text(encoding="utf-8"),
            review_text=args.review.read_text(encoding="utf-8"),
            answer_text=args.answer.read_text(encoding="utf-8"),
            requested_model=args.model,
            api_base=args.api_base,
            seed=args.seed,
            criterion_parallelism=args.criterion_parallelism,
        )
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "reward.json", records.reward)
    _write_json(args.output_dir / "evaluation.json", records.evaluation)
    _write_json(args.output_dir / "usage.json", records.usage)
    print(
        "AutoRubric completed "
        f"{records.evaluation['autorubric']['execution']['criterion_count']} criteria; "
        f"authoritative score={records.reward['score']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
