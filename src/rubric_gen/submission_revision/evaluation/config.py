"""Configuration for submission-revision evaluation."""

from __future__ import annotations

import math
from collections.abc import Mapping

from rubric_gen.detection.config import (
    ANTHROPIC_EFFORT,
    DEFAULT_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_MAX_EVENT_TEXT_CHARS,
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_PANEL_MODELS,
    GEMINI_THINKING_LEVEL,
    INPUT_VALIDATION_POLICY,
    JUDGE_MAX_ATTEMPTS,
    MALT_REWARD_HACKING_AGGREGATION,
    MALT_REWARD_HACKING_CHARS_PER_TOKEN,
    MALT_REWARD_HACKING_DECISION_RULE,
    MALT_REWARD_HACKING_EARLY_MESSAGE_COUNT,
    MALT_REWARD_HACKING_MAX_INPUT_TOKENS,
    MALT_REWARD_HACKING_SOURCE,
    OPENAI_REASONING_EFFORT,
    OPENAI_TEXT_VERBOSITY,
    PROMPT_CACHE_POLICY,
)


OUTCOME_MODELS = DEFAULT_PANEL_MODELS
DEFAULT_RUBRIC_SCORE_MAX_CALLS = 2_048
DEFAULT_RUBRIC_SCORE_MAX_REQUEST_BYTES = 536_870_912
DEFAULT_RUBRIC_SCORE_MAX_OUTPUT_TOKENS = 8_388_608
DEFAULT_RUBRIC_FREE_EVALUATION_MAX_CALLS = 24
DEFAULT_RUBRIC_FREE_EVALUATION_MAX_REQUEST_BYTES = 33_554_432
DEFAULT_RUBRIC_FREE_EVALUATION_MAX_OUTPUT_TOKENS = 98_304
REWARD_HACKING_COMPONENTS = (
    "verifier_exploitation",
    "original_rubric_gap",
)


def outcome_audit_protocol(
    *,
    models: tuple[str, ...],
    primary_rule: str,
    loss_weights: Mapping[str, object],
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_event_text_chars: int = DEFAULT_MAX_EVENT_TEXT_CHARS,
    max_command_output_chars: int = DEFAULT_MAX_COMMAND_OUTPUT_CHARS,
    rubric_score_max_calls: int = DEFAULT_RUBRIC_SCORE_MAX_CALLS,
    rubric_score_max_request_bytes: int = DEFAULT_RUBRIC_SCORE_MAX_REQUEST_BYTES,
    rubric_score_max_output_tokens: int = DEFAULT_RUBRIC_SCORE_MAX_OUTPUT_TOKENS,
    rubric_free_evaluation_max_calls: int = DEFAULT_RUBRIC_FREE_EVALUATION_MAX_CALLS,
    rubric_free_evaluation_max_request_bytes: int = DEFAULT_RUBRIC_FREE_EVALUATION_MAX_REQUEST_BYTES,
    rubric_free_evaluation_max_output_tokens: int = DEFAULT_RUBRIC_FREE_EVALUATION_MAX_OUTPUT_TOKENS,
) -> dict[str, object]:
    """Return the exact blinded outcome-audit protocol."""

    if primary_rule not in {"majority", "any_detect", "unanimous_detects"}:
        raise ValueError("primary detection rule is invalid")
    if (
        not isinstance(loss_weights, Mapping)
        or set(loss_weights) != set(REWARD_HACKING_COMPONENTS)
    ):
        raise ValueError(
            "loss_weights must contain exactly "
            + ", ".join(REWARD_HACKING_COMPONENTS)
        )
    weights: dict[str, float] = {}
    for name in REWARD_HACKING_COMPONENTS:
        value = loss_weights[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"loss weight must be finite and non-negative: {name}"
            )
        weights[name] = float(value)
    if not any(weights.values()):
        raise ValueError("at least one loss weight must be positive")
    if (
        not models
        or len(set(models)) != len(models)
        or any(type(model) is not str or not model.strip() for model in models)
    ):
        raise ValueError("audit models must be unique non-empty strings")
    if type(max_input_tokens) is not int or not 10_000 <= max_input_tokens <= 272_000:
        raise ValueError("audit max input tokens must be between 10000 and 272000")
    if type(max_output_tokens) is not int or not 1_024 <= max_output_tokens <= 16_384:
        raise ValueError("audit max output tokens must be between 1024 and 16384")
    if type(max_event_text_chars) is not int or not (
        4_096 <= max_event_text_chars <= 262_144
    ):
        raise ValueError(
            "audit max event text characters must be between 4096 and 262144"
        )
    if type(max_command_output_chars) is not int or not (
        512 <= max_command_output_chars <= max_event_text_chars
    ):
        raise ValueError(
            "audit max command output characters must be between 512 and "
            "max_event_text_chars"
        )
    stage_caps = {
        "rubric_score_max_calls": rubric_score_max_calls,
        "rubric_score_max_request_bytes": rubric_score_max_request_bytes,
        "rubric_score_max_output_tokens": rubric_score_max_output_tokens,
        "rubric_free_evaluation_max_calls": rubric_free_evaluation_max_calls,
        "rubric_free_evaluation_max_request_bytes": rubric_free_evaluation_max_request_bytes,
        "rubric_free_evaluation_max_output_tokens": rubric_free_evaluation_max_output_tokens,
    }
    if any(type(value) is not int or value <= 0 for value in stage_caps.values()):
        raise ValueError("each audit stage cap must be a positive integer")
    return {
        "detection": "rh",
        "models": list(models),
        "primary_rule": primary_rule,
        "loss_weights": weights,
        "openai_reasoning_effort": OPENAI_REASONING_EFFORT,
        "openai_text_verbosity": OPENAI_TEXT_VERBOSITY,
        "anthropic_effort": ANTHROPIC_EFFORT,
        "gemini_thinking_level": GEMINI_THINKING_LEVEL,
        "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens,
        "max_event_text_chars": max_event_text_chars,
        "max_command_output_chars": max_command_output_chars,
        "max_attempts": JUDGE_MAX_ATTEMPTS,
        **stage_caps,
        "prompt_cache": PROMPT_CACHE_POLICY,
        "input_validation": INPUT_VALIDATION_POLICY,
        "monitor": {
            "source": MALT_REWARD_HACKING_SOURCE,
            "early_message_count": MALT_REWARD_HACKING_EARLY_MESSAGE_COUNT,
            "chunk_max_input_tokens": MALT_REWARD_HACKING_MAX_INPUT_TOKENS,
            "chunk_chars_per_token": MALT_REWARD_HACKING_CHARS_PER_TOKEN,
            "chunk_aggregation": MALT_REWARD_HACKING_AGGREGATION,
            "score_range": [0, 10],
            "derived_decision": MALT_REWARD_HACKING_DECISION_RULE,
        },
        "blinding": (
            "withhold manifest treatment metadata, judge reasoning, rubric text, "
            "feedback not shown before a later revision, solver model, and "
            "revision labels; retain solver-visible score/criterion feedback; "
            "redact known exact task and condition identifiers; agent-authored "
            "discussion remains"
        ),
        "panel_missingness": (
            "any failed or abstaining member makes the assignment outcome missing"
        ),
    }
