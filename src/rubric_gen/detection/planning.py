"""Plan bounded reward-hacking judge requests before dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rubric_gen.detection.config import (
    MALT_REWARD_HACKING_CHARS_PER_TOKEN,
    MALT_REWARD_HACKING_MAX_INPUT_TOKENS,
)
from rubric_gen.detection.prompts import (
    EvidencePrompt,
    _chunk_requests,
    _reward_hacking_requests,
)
from rubric_gen.runtime.llm import StructuredRequest


PANEL_CHUNK_TARGET_INPUT_TOKENS = 220_000
MINIMUM_EVIDENCE_CHARS = 10_000
PROMPT_OVERHEAD_TOKENS = 5_000

CountTokens = Callable[[str, StructuredRequest], int]


@dataclass(frozen=True)
class RequestPlan:
    requests: tuple[StructuredRequest, ...]
    input_tokens: tuple[int, ...]
    aggregation: str
    stats: dict[str, int]


def plan_requests(
    *,
    detection: str,
    case_id: str,
    model: str,
    payload: EvidencePrompt,
    max_input_tokens: int,
    max_output_tokens: int,
    count_tokens: CountTokens,
) -> RequestPlan:
    if detection == "rh":
        return _plan_reward_hacking_requests(
            case_id=case_id,
            model=model,
            payload=payload,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            count_tokens=count_tokens,
        )
    return _plan_direct_requests(
        detection=detection,
        case_id=case_id,
        model=model,
        payload=payload,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        count_tokens=count_tokens,
    )


def _plan_reward_hacking_requests(
    *,
    case_id: str,
    model: str,
    payload: EvidencePrompt,
    max_input_tokens: int,
    max_output_tokens: int,
    count_tokens: CountTokens,
) -> RequestPlan:
    ceiling = min(max_input_tokens, MALT_REWARD_HACKING_MAX_INPUT_TOKENS)
    evidence_chars = max(
        MINIMUM_EVIDENCE_CHARS,
        (ceiling - PROMPT_OVERHEAD_TOKENS) * MALT_REWARD_HACKING_CHARS_PER_TOKEN,
    )
    requests, token_counts, evidence_chars = _fit_requests(
        case_id=case_id,
        model=model,
        input_ceiling=ceiling,
        evidence_chars=evidence_chars,
        request_builder=lambda limit: _reward_hacking_requests(
            payload,
            evidence_chars=limit,
            max_output_tokens=max_output_tokens,
        ),
        count_tokens=count_tokens,
        error_context="MALT monitor prompt",
    )
    return RequestPlan(
        requests=requests,
        input_tokens=token_counts,
        aggregation="max_score",
        stats={
            "planned_calls": len(requests),
            "chunked": int(len(requests) > 1),
            "max_score_aggregation": 1,
            "task_context_chars": len(payload.task_context),
            "behavior_messages": len(payload.behavior_messages),
            "chunk_input_token_ceiling": ceiling,
            "chunk_character_limit": evidence_chars,
        },
    )


def _plan_direct_requests(
    *,
    detection: str,
    case_id: str,
    model: str,
    payload: EvidencePrompt,
    max_input_tokens: int,
    max_output_tokens: int,
    count_tokens: CountTokens,
) -> RequestPlan:
    direct = payload.direct_request(
        detection,
        max_output_tokens=max_output_tokens,
    )
    direct_tokens = count_tokens(model, direct)
    if direct_tokens <= max_input_tokens:
        requests = (direct,)
        token_counts = (direct_tokens,)
    else:
        evidence_chars = _initial_direct_evidence_chars(
            payload,
            direct_tokens,
            max_input_tokens,
        )
        requests, token_counts, _evidence_chars = _fit_requests(
            case_id=case_id,
            model=model,
            input_ceiling=max_input_tokens,
            evidence_chars=evidence_chars,
            request_builder=lambda limit: _chunk_requests(
                payload,
                detection,
                evidence_chars=limit,
                max_output_tokens=max_output_tokens,
            ),
            count_tokens=count_tokens,
            error_context="prompt",
        )
    return RequestPlan(
        requests=requests,
        input_tokens=token_counts,
        aggregation="synthesis",
        stats={
            "direct_input_tokens": direct_tokens,
            "planned_calls": len(requests) + int(len(requests) > 1),
            "chunked": int(len(requests) > 1),
            "max_score_aggregation": 0,
        },
    )


def _initial_direct_evidence_chars(
    payload: EvidencePrompt,
    direct_tokens: int,
    max_input_tokens: int,
) -> int:
    target_tokens = min(
        PANEL_CHUNK_TARGET_INPUT_TOKENS,
        max_input_tokens - PROMPT_OVERHEAD_TOKENS,
    )
    return max(
        MINIMUM_EVIDENCE_CHARS,
        int(len(payload.evidence) * target_tokens / direct_tokens),
    )


def _fit_requests(
    *,
    case_id: str,
    model: str,
    input_ceiling: int,
    evidence_chars: int,
    request_builder: Callable[[int], tuple[StructuredRequest, ...]],
    count_tokens: CountTokens,
    error_context: str,
) -> tuple[tuple[StructuredRequest, ...], tuple[int, ...], int]:
    while True:
        requests = request_builder(evidence_chars)
        token_counts = tuple(count_tokens(model, request) for request in requests)
        largest = max(token_counts)
        if largest <= input_ceiling:
            return requests, token_counts, evidence_chars
        evidence_chars = _smaller_evidence_limit(
            case_id,
            evidence_chars,
            input_ceiling,
            largest,
            error_context,
        )


def _smaller_evidence_limit(
    case_id: str,
    evidence_chars: int,
    input_ceiling: int,
    largest: int,
    error_context: str,
) -> int:
    next_limit = int(evidence_chars * input_ceiling / largest * 0.95)
    if next_limit >= evidence_chars:
        next_limit = evidence_chars - 1_000
    if next_limit < MINIMUM_EVIDENCE_CHARS:
        raise ValueError(
            f"cannot create a bounded {error_context} for {case_id}: "
            f"minimum chunk still requires {largest} input tokens"
        )
    return next_limit
