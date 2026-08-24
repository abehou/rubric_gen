"""Execute and persist reward-hacking model-panel audits."""

from __future__ import annotations

import json
import math
import os
import shutil
import threading
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.evidence.index import index_implementation_sha256
from rubric_gen.reward_hacking.metrics import detection_rates, plot_detection_rates
from rubric_gen.reward_hacking.protocol import (
    ANTHROPIC_RH_EFFORT,
    DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_RH_MAX_EVENT_TEXT_CHARS,
    DEFAULT_RH_MAX_INPUT_TOKENS,
    DEFAULT_RH_MAX_OUTPUT_TOKENS,
    GEMINI_RH_THINKING_LEVEL,
    MALT_RH_AGGREGATION,
    MALT_RH_CHARS_PER_TOKEN,
    MALT_RH_DECISION_RULE,
    MALT_RH_EARLY_MESSAGE_COUNT,
    MALT_RH_MONITOR_MAX_INPUT_TOKENS,
    MALT_RH_MONITOR_SOURCE,
    OPENAI_RH_REASONING_EFFORT,
    OPENAI_RH_TEXT_VERBOSITY,
    RH_INPUT_VALIDATION_POLICY,
    RH_PROMPT_CACHE_POLICY,
)
from rubric_gen.reward_hacking.review import (
    CostBudgetExceeded,
    _aggregate_rh_scores,
    _chunk_requests,
    _extract,
    _extract_model_output,
    _retry_disposition,
    _rh_requests,
    _synthesis_request,
    _validate_rh_verdict,
)
from rubric_gen.reward_hacking.sources import AuditCase, AuditSource
from rubric_gen.reward_hacking.targets import detection_target
from rubric_gen.runtime.llm import (
    GenerationResult,
    HOSTED_REQUEST_TIMEOUT_SECONDS,
    StructuredRequest,
    count_input_tokens,
    estimate_input_tokens,
    generate_structured,
    generate_structured_vllm,
    openai_prompt_cache_arguments,
    request_parameters_for_model,
    metadata_value,
)
from rubric_gen.runtime.pricing import (
    ANTHROPIC_PRICES_PER_MILLION,
    GEMINI_PRICES_PER_MILLION,
    HOSTED_PRICES_PER_MILLION,
    OPENAI_LONG_CONTEXT_THRESHOLD,
    OPENAI_LONG_INPUT_MULTIPLIER,
    OPENAI_LONG_OUTPUT_MULTIPLIER,
    OPENAI_PRICES_PER_MILLION,
    PRICING_AS_OF,
    PRICING_SOURCES,
)
from rubric_gen.runtime.progress import TerminalProgress


DEFAULT_PANEL_MAX_COST_USD = 50.0
PANEL_CHUNK_TARGET_INPUT_TOKENS = 220_000


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
        return (
            "chunk"
            if self.chunked or self.aggregation == "max_score"
            else "direct"
        )


class RewardHackingJudgeRunner:
    def __init__(
        self, config: RewardHackingJudgeConfig,
        *, generate_response: Callable[[str, StructuredRequest], GenerationResult] = generate_structured,
        generate_vllm_response: Callable[
            [str, StructuredRequest, str], GenerationResult
        ] = generate_structured_vllm,
        count_tokens: Callable[[str, StructuredRequest], int] | None = None,
    ) -> None:
        self.config = config
        target = detection_target(config.detection)
        self.generate_response = generate_response
        self.generate_vllm_response = generate_vllm_response
        self.count_tokens = (
            count_tokens
            if count_tokens is not None
            else (
                count_input_tokens
                if generate_response is generate_structured
                else estimate_input_tokens
            )
        )
        self._budget_lock = threading.Lock()
        self._spent_usd = 0.0
        self._spent_by_model: dict[str, float] = {}
        self._unverified_failure_risk_usd = 0.0
        self._reserved_usd = 0.0
        self._circuit_open: dict[str, str] = {}
        self.run_provenance = {
            "implementation_sha256": sha256_file(Path(__file__)),
            "evidence_index_sha256": index_implementation_sha256(),
            "detection": config.detection,
            "detection_target": target.provenance(),
            "models": list(config.models),
            "max_concurrency": config.max_concurrency,
            "max_retries": config.max_retries,
            "max_input_tokens": config.max_input_tokens,
            "max_output_tokens": config.max_output_tokens,
            "max_event_text_chars": config.max_event_text_chars,
            "max_command_output_chars": config.max_command_output_chars,
            "max_cost_usd": config.max_cost_usd,
            "execution": config.execution,
            "primary_rule": config.primary_rule,
            "source": config.source.provenance,
            "openai_reasoning_effort": OPENAI_RH_REASONING_EFFORT,
            "openai_text_verbosity": OPENAI_RH_TEXT_VERBOSITY,
            "anthropic_effort": ANTHROPIC_RH_EFFORT,
            "gemini_thinking_level": GEMINI_RH_THINKING_LEVEL,
            "prompt_cache": RH_PROMPT_CACHE_POLICY,
            "input_validation": RH_INPUT_VALIDATION_POLICY,
            "rh_monitor": (
                {
                    "source": MALT_RH_MONITOR_SOURCE,
                    "early_message_count": MALT_RH_EARLY_MESSAGE_COUNT,
                    "chunk_max_input_tokens": MALT_RH_MONITOR_MAX_INPUT_TOKENS,
                    "chars_per_token": MALT_RH_CHARS_PER_TOKEN,
                    "aggregation": MALT_RH_AGGREGATION,
                    "derived_decision_rule": MALT_RH_DECISION_RULE,
                }
                if config.detection == "rh"
                else None
            ),
            "model_requests": {
                model: request_parameters_for_model(
                    model,
                    base_url=config.base_urls.get(model),
                    max_output_tokens=config.max_output_tokens,
                )
                for model in config.models
            },
            "pricing": {
                "sources": PRICING_SOURCES,
                "as_of": PRICING_AS_OF,
                "prices_per_million": HOSTED_PRICES_PER_MILLION,
                "openai_long_context": {
                    "threshold_input_tokens": OPENAI_LONG_CONTEXT_THRESHOLD,
                    "input_multiplier": OPENAI_LONG_INPUT_MULTIPLIER,
                    "output_multiplier": OPENAI_LONG_OUTPUT_MULTIPLIER,
                },
            },
        }
        self.run_provenance_sha256 = sha256_text(json.dumps(
            self.run_provenance,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ))

    def _initialize_cost_state(self) -> None:
        """Restore a cumulative, crash-conservative standard-request budget."""

        path = self.config.output_dir / "cost-state.json"
        if path.is_symlink():
            raise ValueError("cost state path is not a regular file")
        if not path.is_file():
            if self.config.resume:
                raise ValueError("resumed run has no strict cost-state.json")
            with self._budget_lock:
                self._persist_cost_state_locked()
            return
        if not self.config.resume:
            raise FileExistsError("cost state exists; rerun with --resume")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid cost state: {path}") from exc
        if (
            not isinstance(state, dict)
            or set(state) != {
                "kind",
                "run_provenance_sha256",
                "observed_api_usd",
                "observed_by_model_usd",
                "unverified_failed_request_risk_usd",
                "reserved_api_usd",
                "budget_usd",
            }
            or state.get("kind") != "reward-hacking-standard-cost-state"
            or state.get("run_provenance_sha256") != self.run_provenance_sha256
            or state.get("budget_usd") != self.config.max_cost_usd
        ):
            raise ValueError("cost state does not match this run")
        values: dict[str, float] = {}
        for key in (
            "observed_api_usd",
            "unverified_failed_request_risk_usd",
            "reserved_api_usd",
        ):
            value = state.get(key)
            numeric = (
                float(value)
                if not isinstance(value, bool) and isinstance(value, (int, float))
                else None
            )
            if (
                numeric is None
                or not math.isfinite(numeric)
                or numeric < -1e-9
            ):
                raise ValueError(f"cost state has invalid {key}")
            values[key] = max(0.0, numeric)
        raw_by_model = state.get("observed_by_model_usd")
        if not isinstance(raw_by_model, dict) or any(
            model not in self.config.models
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for model, value in raw_by_model.items()
        ):
            raise ValueError("cost state has invalid observed_by_model_usd")
        by_model = {
            str(model): float(value) for model, value in raw_by_model.items()
        }
        if not math.isclose(
            sum(by_model.values()), values["observed_api_usd"], abs_tol=1e-9
        ):
            raise ValueError("cost state model costs do not sum to observed cost")
        with self._budget_lock:
            self._spent_usd = values["observed_api_usd"]
            self._spent_by_model = by_model
            self._unverified_failure_risk_usd = (
                values["unverified_failed_request_risk_usd"]
                + values["reserved_api_usd"]
            )
            self._reserved_usd = 0.0
            self._persist_cost_state_locked()

    def _persist_cost_state_locked(self) -> None:
        write_json_atomic(self.config.output_dir / "cost-state.json", {
            "kind": "reward-hacking-standard-cost-state",
            "run_provenance_sha256": self.run_provenance_sha256,
            "observed_api_usd": self._spent_usd,
            "observed_by_model_usd": dict(sorted(self._spent_by_model.items())),
            "unverified_failed_request_risk_usd": (
                self._unverified_failure_risk_usd
            ),
            "reserved_api_usd": self._reserved_usd,
            "budget_usd": self.config.max_cost_usd,
        })

    def _write_or_validate_run_provenance(self) -> None:
        path = self.config.output_dir / "run-provenance.json"
        expected = {
            **self.run_provenance,
            "sha256": self.run_provenance_sha256,
        }
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid run provenance: {path}") from exc
            if existing != expected:
                raise ValueError(
                    "existing run provenance does not exactly match the requested run"
                )
            return
        if self.config.resume:
            raise ValueError("resumed run has no strict run-provenance.json")
        write_json_atomic(path, expected)

    def _payload(self, case: AuditCase) -> EvidencePrompt:
        return self.config.source.prompt(
            case,
            self.config.detection,
            max_event_text_chars=self.config.max_event_text_chars,
            max_command_output_chars=self.config.max_command_output_chars,
        )

    def _prepare_job(
        self,
        case: AuditCase,
        model: str,
        payload: EvidencePrompt,
    ) -> PreparedJob:
        if self.config.detection == "rh":
            input_ceiling = min(
                self.config.max_input_tokens,
                MALT_RH_MONITOR_MAX_INPUT_TOKENS,
            )
            evidence_chars = max(
                10_000,
                (input_ceiling - 5_000) * MALT_RH_CHARS_PER_TOKEN,
            )
            while True:
                requests = _rh_requests(
                    payload,
                    evidence_chars=evidence_chars,
                    max_output_tokens=self.config.max_output_tokens,
                )
                token_counts = tuple(
                    self.count_tokens(model, request) for request in requests
                )
                largest = max(token_counts)
                if largest <= input_ceiling:
                    break
                next_limit = int(evidence_chars * input_ceiling / largest * 0.95)
                if next_limit >= evidence_chars:
                    next_limit = evidence_chars - 1_000
                if next_limit < 10_000:
                    raise ValueError(
                        f"cannot create a bounded MALT monitor prompt for {case.case_id}: "
                        f"minimum chunk still requires {largest} input tokens"
                    )
                evidence_chars = next_limit
            aggregation = "max_score"
            planning_stats = {
                "planned_calls": len(requests),
                "chunked": int(len(requests) > 1),
                "max_score_aggregation": 1,
                "persistent_messages": min(
                    len(payload.messages), MALT_RH_EARLY_MESSAGE_COUNT
                ),
                "chunk_input_token_ceiling": input_ceiling,
                "chunk_character_limit": evidence_chars,
            }
        else:
            direct = payload.direct_request(
                self.config.detection,
                max_output_tokens=self.config.max_output_tokens,
            )
            direct_tokens = self.count_tokens(model, direct)
            if direct_tokens <= self.config.max_input_tokens:
                requests, token_counts = (direct,), (direct_tokens,)
            else:
                evidence_chars = max(
                    10_000,
                    int(
                        len(payload.evidence)
                        * min(
                            PANEL_CHUNK_TARGET_INPUT_TOKENS,
                            self.config.max_input_tokens - 5_000,
                        )
                        / direct_tokens
                    ),
                )
                while True:
                    requests = _chunk_requests(
                        payload,
                        self.config.detection,
                        evidence_chars=evidence_chars,
                        max_output_tokens=self.config.max_output_tokens,
                    )
                    token_counts = tuple(
                        self.count_tokens(model, request) for request in requests
                    )
                    largest = max(token_counts)
                    if largest <= self.config.max_input_tokens:
                        break
                    next_limit = int(
                        evidence_chars
                        * self.config.max_input_tokens
                        / largest
                        * 0.95
                    )
                    if next_limit >= evidence_chars:
                        next_limit = evidence_chars - 1_000
                    if next_limit < 10_000:
                        raise ValueError(
                            f"cannot create a bounded prompt for {case.case_id}: "
                            f"minimum chunk still requires {largest} input tokens"
                        )
                    evidence_chars = next_limit
            aggregation = "synthesis"
            planning_stats = {
                "direct_input_tokens": direct_tokens,
                "planned_calls": len(requests) + (1 if len(requests) > 1 else 0),
                "chunked": int(len(requests) > 1),
                "max_score_aggregation": 0,
            }
        return PreparedJob(
            case=case,
            model=model,
            requests=requests,
            input_tokens=token_counts,
            compact_stats={
                **payload.stats,
                **planning_stats,
            },
            aggregation=aggregation,
        )

    @staticmethod
    def _cache_write_reservation_tokens(
        model: str,
        request: StructuredRequest,
        input_tokens: int,
    ) -> int:
        """Conservatively reserve cache-write pricing only for its prefix."""

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

    @staticmethod
    def _request_cost(
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

    def _prepare_jobs(self) -> tuple[PreparedJob, ...]:
        cases = sorted(self.config.source.cases, key=lambda case: case.sort_key)
        total = len(cases) * len(self.config.models)
        jobs = []
        with TerminalProgress(
            total=total,
            description="Audit preparation",
            unit="job",
        ) as progress:
            for case in cases:
                progress.set_status(f"loading {case.case_id}")
                payload = self._payload(case)
                for model in self.config.models:
                    progress.set_status(f"planning {case.case_id} for {model}")
                    jobs.append(self._prepare_job(case, model, payload))
                    progress.update()
        return tuple(jobs)

    @staticmethod
    def _usage_tokens(generation: GenerationResult) -> dict[str, int] | None:
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

    def _generate_budgeted(
        self,
        model: str,
        request: StructuredRequest,
        *,
        input_tokens: int,
        base_url: str | None,
    ) -> GenerationResult:
        with self._budget_lock:
            if model in self._circuit_open:
                raise RuntimeError(
                    f"provider circuit is open for {model}: {self._circuit_open[model]}"
                )
            cache_write_tokens = self._cache_write_reservation_tokens(
                model,
                request,
                input_tokens,
            )
            reservation = self._request_cost(
                model,
                input_tokens,
                self.config.max_output_tokens,
                cache_write_input_tokens=cache_write_tokens,
            ) or 0.0
            if self.config.max_cost_usd is not None and (
                self._spent_usd + self._reserved_usd + reservation
                + self._unverified_failure_risk_usd
                > self.config.max_cost_usd
            ):
                raise CostBudgetExceeded(
                    f"dispatching {model} would exceed the ${self.config.max_cost_usd:.2f} "
                    "run budget"
                )
            self._reserved_usd += reservation
            self._persist_cost_state_locked()
        try:
            generation = (
                self.generate_vllm_response(model, request, base_url)
                if base_url is not None
                else self.generate_response(model, request)
            )
        except Exception:
            with self._budget_lock:
                self._reserved_usd = max(0.0, self._reserved_usd - reservation)
                self._unverified_failure_risk_usd += reservation
                self._persist_cost_state_locked()
            raise
        usage = self._usage_tokens(generation)
        actual = (
            self._request_cost(model, **usage)
            if usage is not None
            else reservation
        )
        with self._budget_lock:
            self._reserved_usd = max(0.0, self._reserved_usd - reservation)
            self._spent_usd += actual or 0.0
            if actual is not None:
                self._spent_by_model[model] = (
                    self._spent_by_model.get(model, 0.0) + actual
                )
            self._persist_cost_state_locked()
        return generation

    def run(self) -> int:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._write_or_validate_run_provenance()
            if self.config.execution == "standard":
                self._initialize_cost_state()
        except ValueError:
            if not self.config.resume:
                raise
            self._replace_incompatible_output()
            self.config = replace(self.config, resume=False)
            self._write_or_validate_run_provenance()
            if self.config.execution == "standard":
                self._initialize_cost_state()
        jobs = self._prepare_jobs()
        if self.config.execution == "batch":
            return self._run_batch(jobs)
        records: list[dict[str, object]] = []
        with TerminalProgress(
            total=len(jobs), description="Reward-hacking model panel", unit="judgment"
        ) as progress:
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                grouped: dict[tuple[str, str], deque[PreparedJob]] = {}
                for job in jobs:
                    grouped.setdefault(
                        self._standard_cache_group(job), deque()
                    ).append(job)
                pending = deque(grouped.values())
                active: dict[
                    Future[dict[str, object]],
                    tuple[deque[PreparedJob], PreparedJob],
                ] = {}

                def submit_next(group: deque[PreparedJob]) -> None:
                    job = group.popleft()
                    active[pool.submit(self._one_with_retries, job)] = (group, job)

                while pending and len(active) < self.config.max_concurrency:
                    submit_next(pending.popleft())
                while active:
                    completed, _ = wait(tuple(active), return_when=FIRST_COMPLETED)
                    for future in completed:
                        group, job = active.pop(future)
                        try:
                            records.append(future.result())
                        except Exception as exc:
                            records.append({"case_id": job.case.case_id,
                                            "source_kind": job.source_kind,
                                            "source_path": str(job.case.path),
                                            "provider": job.model,
                                            "model": job.model, "status": "failed",
                                            "error_type": type(exc).__name__,
                                            "error": str(exc)})
                        progress.update()
                        if group:
                            submit_next(group)
                        elif pending:
                            submit_next(pending.popleft())
        return self._finish(records, jobs)

    def _replace_incompatible_output(self) -> None:
        root = self.config.output_dir
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(f"invalid reward-hacking output directory: {root}")
        shutil.rmtree(root)
        root.mkdir(parents=True)

    @staticmethod
    def _standard_cache_group(job: PreparedJob) -> tuple[str, str]:
        """Serialize identical provider-cache prefixes to avoid duplicate writes."""

        return (job.model, job.requests[0].prompt_cache_key())

    def _finish(
        self, records: list[dict[str, object]], jobs: tuple[PreparedJob, ...]
    ) -> int:
        records.sort(key=lambda row: (str(row["case_id"]), str(row["model"])))
        summary = {"kind": "reward-hacking-model-panel",
                   "models": list(self.config.models),
                   "base_urls": self.config.base_urls,
                   "max_retries": self.config.max_retries,
                   "detection": self.config.detection,
                   "detection_target": detection_target(
                       self.config.detection
                   ).provenance(),
                   "primary_rule": self.config.primary_rule,
                   "rh_monitor": self.run_provenance.get("rh_monitor"),
                   "source": self.config.source.provenance,
                   "run_provenance_sha256": self.run_provenance_sha256,
                   "run_provenance": self.run_provenance,
                   "cost": {
                       "observed_api_usd": self._spent_usd,
                       "observed_by_model_usd": dict(
                           sorted(self._spent_by_model.items())
                       ),
                       "unverified_failed_request_risk_usd": (
                           self._unverified_failure_risk_usd
                       ),
                       "budget_usd": self.config.max_cost_usd,
                       "pricing_sources": PRICING_SOURCES,
                       "pricing_as_of": PRICING_AS_OF,
                   },
                   "records": records}
        write_json_atomic(self.config.output_dir / "summary.json", summary)
        rates = detection_rates(summary)
        write_json_atomic(self.config.output_dir / "detection-rates.json", rates)
        plot_detection_rates(rates, self.config.output_dir / "detection-rates.png")
        failures = sum(row["status"] == "failed" for row in records)
        return 1 if failures else 0

    def _batch_body(self, model: str, request: StructuredRequest) -> dict[str, object]:
        return {
            "model": model,
            "input": request.openai_input(model),
            "max_output_tokens": self.config.max_output_tokens,
            "reasoning": {"effort": OPENAI_RH_REASONING_EFFORT},
            "text": request.text_config(),
            "truncation": "disabled",
            "store": False,
            **openai_prompt_cache_arguments(model, request),
        }

    @staticmethod
    def _response_body_text(body: dict[str, object]) -> str:
        pieces: list[str] = []
        output = body.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        text = block.get("text")
                        if isinstance(text, str):
                            pieces.append(text)
        text = "\n".join(pieces)
        if not text.strip():
            raise RuntimeError("OpenAI Batch response contained no output text")
        return text

    def _generation_from_batch(
        self, model: str, body: dict[str, object]
    ) -> GenerationResult:
        effective_model, response_id = body.get("model"), body.get("id")
        if type(effective_model) is not str or type(response_id) is not str:
            raise RuntimeError("OpenAI Batch response omitted model identity")
        return GenerationResult(
            text=self._response_body_text(body),
            provider="openai",
            requested_model=model,
            effective_model=effective_model,
            response_id=response_id,
            request_parameters=request_parameters_for_model(
                model, max_output_tokens=self.config.max_output_tokens
            ),
            provider_metadata={
                "batch": True,
                "created_at": metadata_value(body.get("created_at")),
                "service_tier": metadata_value(body.get("service_tier")),
                "usage": metadata_value(body.get("usage")),
            },
        )

    @staticmethod
    def _download_text(client: object, file_id: str) -> str:
        content = client.files.content(file_id)  # type: ignore[attr-defined]
        text_value = getattr(content, "text", None)
        if isinstance(text_value, str):
            return text_value
        read = getattr(content, "read", None)
        value = read() if callable(read) else bytes(content)
        return value.decode() if isinstance(value, bytes) else str(value)

    def _submit_batch(
        self,
        client: object,
        state: dict[str, object],
        entries: list[tuple[str, StructuredRequest]],
    ) -> None:
        phase = str(state["phase"])
        attempt = int(state["attempt"])
        path = self.config.output_dir / f"batch-{phase}-{attempt:02d}.jsonl"
        lines = [
            json.dumps({
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": self._batch_body(self.config.models[0], request),
            }, ensure_ascii=False, separators=(",", ":"))
            for custom_id, request in entries
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with path.open("rb") as stream:
            uploaded = client.files.create(file=stream, purpose="batch")  # type: ignore[attr-defined]
        batch = client.batches.create(  # type: ignore[attr-defined]
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={
                "kind": "reward-hacking-forensic-evaluation",
                "run": self.run_provenance_sha256[:32],
                "phase": phase,
            },
        )
        state.update({
            "status": batch.status,
            "batch_id": batch.id,
            "input_file_id": uploaded.id,
            "custom_ids": [custom_id for custom_id, _ in entries],
            "local_input": path.name,
        })
        write_json_atomic(self.config.output_dir / "batch-state.json", state)
        print(
            f"Submitted OpenAI Batch {batch.id} ({phase}, {len(entries)} requests). "
            "Rerun the identical command with --resume to collect it."
        )

    @staticmethod
    def _batch_initial_entries(
        jobs: tuple[PreparedJob, ...], custom_ids: set[str] | None = None
    ) -> list[tuple[str, StructuredRequest]]:
        entries = [
            (f"j{job_index:05d}-r{request_index:03d}", request)
            for job_index, job in enumerate(jobs)
            for request_index, request in enumerate(job.requests)
        ]
        return entries if custom_ids is None else [
            entry for entry in entries if entry[0] in custom_ids
        ]

    def _batch_synthesis_entries(
        self,
        jobs: tuple[PreparedJob, ...],
        initial_results: dict[str, object],
        custom_ids: set[str] | None = None,
    ) -> list[tuple[str, StructuredRequest]]:
        entries: list[tuple[str, StructuredRequest]] = []
        for job_index, job in enumerate(jobs):
            if not job.requires_synthesis:
                continue
            verdicts: list[dict[str, object]] = []
            complete = True
            for request_index in range(len(job.requests)):
                result = initial_results.get(
                    f"j{job_index:05d}-r{request_index:03d}"
                )
                if not isinstance(result, dict) or not isinstance(
                    result.get("verdict"), dict
                ):
                    complete = False
                    break
                verdicts.append(result["verdict"])
            if complete:
                payload = self._payload(job.case)
                request = _synthesis_request(
                    payload,
                    self.config.detection,
                    verdicts,
                    max_output_tokens=self.config.max_output_tokens,
                )
                tokens = self.count_tokens(job.model, request)
                if tokens > self.config.max_input_tokens:
                    raise ValueError(
                        f"chunk synthesis requires {tokens} tokens, above the "
                        f"{self.config.max_input_tokens} token ceiling"
                    )
                entries.append((f"j{job_index:05d}-s000", request))
        return entries if custom_ids is None else [
            entry for entry in entries if entry[0] in custom_ids
        ]

    def _collect_batch_files(
        self, client: object, batch: object
    ) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
        outputs: dict[str, dict[str, object]] = {}
        errors: dict[str, dict[str, object]] = {}
        output_file_id = getattr(batch, "output_file_id", None)
        if isinstance(output_file_id, str):
            text = self._download_text(client, output_file_id)
            (self.config.output_dir / f"{batch.id}-output.jsonl").write_text(text)
            for line in text.splitlines():
                row = json.loads(line)
                custom_id = row.get("custom_id")
                response = row.get("response")
                if isinstance(custom_id, str) and isinstance(response, dict):
                    body = response.get("body")
                    if response.get("status_code") == 200 and isinstance(body, dict):
                        outputs[custom_id] = body
                    else:
                        errors[custom_id] = {
                            "status_code": response.get("status_code"),
                            "error": body,
                        }
        error_file_id = getattr(batch, "error_file_id", None)
        if isinstance(error_file_id, str):
            text = self._download_text(client, error_file_id)
            (self.config.output_dir / f"{batch.id}-errors.jsonl").write_text(text)
            for line in text.splitlines():
                row = json.loads(line)
                custom_id = row.get("custom_id")
                if isinstance(custom_id, str):
                    errors[custom_id] = {
                        "status_code": None,
                        "error": row.get("error"),
                    }
        return outputs, errors

    def _batch_result(
        self, custom_id: str, body: dict[str, object]
    ) -> dict[str, object]:
        generation = self._generation_from_batch(self.config.models[0], body)
        usage = self._usage_tokens(generation)
        if usage is not None:
            model = self.config.models[0]
            cost = (self._request_cost(model, **usage) or 0.0) * 0.5
            self._spent_usd += cost
            self._spent_by_model[model] = (
                self._spent_by_model.get(model, 0.0) + cost
            )
        try:
            verdict = _extract_model_output(generation.text, self.config.detection)
        except Exception as exc:
            setattr(exc, "batch_cost_accounted", usage is not None)
            raise
        return {
            "custom_id": custom_id,
            "text": generation.text,
            "generation": generation.provenance(),
            "verdict": verdict,
        }

    def _batch_records(
        self, jobs: tuple[PreparedJob, ...], state: dict[str, object]
    ) -> list[dict[str, object]]:
        initial = state.get("initial_results")
        synthesis = state.get("synthesis_results")
        failures = {
            **(state.get("initial_failures") if isinstance(state.get("initial_failures"), dict) else {}),
            **(state.get("synthesis_failures") if isinstance(state.get("synthesis_failures"), dict) else {}),
        }
        assert isinstance(initial, dict)
        synthesis = synthesis if isinstance(synthesis, dict) else {}
        records: list[dict[str, object]] = []
        for job_index, job in enumerate(jobs):
            case_id = job.case.case_id
            ids = [
                f"j{job_index:05d}-r{index:03d}"
                for index in range(len(job.requests))
            ]
            synthesis_id = f"j{job_index:05d}-s000"
            initial_results = [initial.get(item) for item in ids]
            result: dict[str, object] | None
            verdict: dict[str, object] | None = None
            if job.aggregation == "max_score" and all(
                isinstance(value, dict) for value in initial_results
            ):
                chunk_scores = [
                    value["verdict"]
                    for value in initial_results
                    if isinstance(value, dict)
                ]
                if all(isinstance(value, dict) for value in chunk_scores):
                    verdict = _aggregate_rh_scores(chunk_scores)
                    selected = int(verdict["selected_chunk"]) - 1
                    selected_result = initial_results[selected]
                    result = (
                        selected_result
                        if isinstance(selected_result, dict)
                        else None
                    )
                else:
                    result = None
            elif job.requires_synthesis:
                selected_result = synthesis.get(synthesis_id)
                result = selected_result if isinstance(selected_result, dict) else None
                if result is not None and isinstance(result.get("verdict"), dict):
                    verdict = result["verdict"]
            else:
                selected_result = initial_results[0]
                result = selected_result if isinstance(selected_result, dict) else None
                if result is not None and isinstance(result.get("verdict"), dict):
                    verdict = result["verdict"]
            relevant_ids = (*ids, synthesis_id) if job.requires_synthesis else tuple(ids)
            failed_ids = [item for item in relevant_ids if item in failures]
            if result is None or verdict is None:
                error = failures.get(failed_ids[0], {}) if failed_ids else {}
                records.append({
                    "case_id": case_id,
                    "source_kind": job.source_kind,
                    "source_path": str(job.case.path),
                    "provider": job.model,
                    "model": job.model,
                    "status": "failed",
                    "error_type": "BatchRequestError",
                    "error": json.dumps(error, default=str),
                    "attempt_count": int(state.get("attempt", 1)),
                    "max_retries": self.config.max_retries,
                    "retry_exhausted": False,
                })
                continue
            generation_entries = [
                {"stage": job.request_stage,
                 "index": index + 1,
                 "input_tokens": job.input_tokens[index],
                 "generation": initial[item]["generation"]}
                for index, item in enumerate(ids)
                if isinstance(initial.get(item), dict)
            ]
            prompt_entries = [
                {"stage": job.request_stage,
                 "index": index + 1,
                 "input_tokens": job.input_tokens[index],
                 "prompt": job.requests[index].flat_prompt()}
                for index in range(len(job.requests))
            ]
            response_entries = [
                {"stage": job.request_stage,
                 "index": index + 1,
                 "text": initial[item]["text"]}
                for index, item in enumerate(ids)
                if isinstance(initial.get(item), dict)
            ]
            if job.requires_synthesis:
                verdicts = [initial[item]["verdict"] for item in ids]
                synthesis_request = _synthesis_request(
                    self._payload(job.case),
                    self.config.detection,
                    verdicts,
                    max_output_tokens=self.config.max_output_tokens,
                )
                synthesis_tokens = self.count_tokens(job.model, synthesis_request)
                generation_entries.append({
                    "stage": "synthesis", "index": 1,
                    "input_tokens": synthesis_tokens,
                    "generation": result["generation"],
                })
                prompt_entries.append({
                    "stage": "synthesis", "index": 1,
                    "input_tokens": synthesis_tokens,
                    "prompt": synthesis_request.flat_prompt(),
                })
                response_entries.append({
                    "stage": "synthesis", "index": 1, "text": result["text"]
                })
            source_key = job.case.case_id
            root = (
                self.config.output_dir / "cases" / source_key
                / job.model.replace("/", "_")
            )
            root.mkdir(parents=True, exist_ok=True)
            artifact_values = {
                "prompts.json": prompt_entries,
                "responses.json": response_entries,
                "generations.json": generation_entries,
                "verdict.json": verdict,
            }
            for filename, value in artifact_values.items():
                write_json_atomic(root / filename, value)
            write_json_atomic(root / "metadata.json", {
                "execution": "batch",
                "compact_evidence": job.compact_stats,
                "attempt_count": int(state.get("attempt", 1)),
                "generations": generation_entries,
                "artifacts": {
                    filename.removesuffix(".json") + "_sha256": sha256_file(
                        root / filename
                    )
                    for filename in artifact_values
                },
            })
            records.append({
                "case_id": case_id,
                "source_kind": job.source_kind,
                "source_path": str(job.case.path),
                "provider": job.model,
                "model": job.model,
                "status": "completed",
                "compact_evidence": job.compact_stats,
                "generation": result["generation"],
                "generations": generation_entries,
                "attempt_count": int(state.get("attempt", 1)),
                "max_retries": self.config.max_retries,
                "retry_exhausted": False,
                "verdict": verdict,
            })
        return records

    def _run_batch(self, jobs: tuple[PreparedJob, ...]) -> int:
        from openai import OpenAI

        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        client = OpenAI(
            api_key=key,
            timeout=HOSTED_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
        state_path = self.config.output_dir / "batch-state.json"
        if not state_path.is_file():
            if self.config.resume:
                raise ValueError("resumed Batch run has no batch-state.json")
            state: dict[str, object] = {
                "kind": "reward-hacking-openai-batch",
                "run_provenance_sha256": self.run_provenance_sha256,
                "phase": "initial",
                "attempt": 1,
                "initial_results": {},
                "initial_failures": {},
                "synthesis_results": {},
                "synthesis_failures": {},
                "observed_api_usd": 0.0,
                "observed_by_model_usd": {},
                "unverified_failed_request_risk_usd": 0.0,
            }
            self._submit_batch(client, state, self._batch_initial_entries(jobs))
            return 0
        if not self.config.resume:
            raise FileExistsError("Batch state exists; rerun with --resume")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if (
            not isinstance(state, dict)
            or set(state) != {
                "kind", "run_provenance_sha256", "phase", "attempt",
                "initial_results", "initial_failures", "synthesis_results",
                "synthesis_failures", "observed_api_usd",
                "observed_by_model_usd", "unverified_failed_request_risk_usd",
                "status", "batch_id", "input_file_id", "custom_ids",
                "local_input",
            }
            or state.get("kind") != "reward-hacking-openai-batch"
            or state.get("run_provenance_sha256") != self.run_provenance_sha256
        ):
            raise ValueError("Batch state provenance does not match this run")
        if state.get("phase") == "complete" and (
            self.config.output_dir / "summary.json"
        ).is_file():
            return 0
        observed_cost = state.get("observed_api_usd", 0.0)
        self._spent_usd = (
            float(observed_cost) if isinstance(observed_cost, (int, float)) else 0.0
        )
        raw_by_model = state.get("observed_by_model_usd", {})
        self._spent_by_model = (
            {
                str(model): float(value)
                for model, value in raw_by_model.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
            if isinstance(raw_by_model, dict)
            else {}
        )
        risk_value = state.get("unverified_failed_request_risk_usd", 0.0)
        self._unverified_failure_risk_usd = (
            float(risk_value) if isinstance(risk_value, (int, float)) else 0.0
        )
        batch = client.batches.retrieve(str(state["batch_id"]))
        state["status"] = batch.status
        if batch.status not in {"completed", "failed", "expired", "cancelled"}:
            write_json_atomic(state_path, state)
            print(f"OpenAI Batch {batch.id} is {batch.status}; retry --resume later.")
            return 0
        outputs, errors = self._collect_batch_files(client, batch)
        if batch.status != "completed" and not errors:
            errors = {
                custom_id: {
                    "status_code": None,
                    "error": {"type": "batch_" + batch.status},
                }
                for custom_id in state.get("custom_ids", [])
                if isinstance(custom_id, str)
            }
        phase = str(state["phase"])
        result_key = f"{phase}_results"
        failure_key = f"{phase}_failures"
        results = state.get(result_key)
        failures = state.get(failure_key)
        assert isinstance(results, dict) and isinstance(failures, dict)
        for custom_id, body in outputs.items():
            try:
                results[custom_id] = self._batch_result(custom_id, body)
            except Exception as exc:
                retryable, opens_circuit = _retry_disposition(exc)
                errors[custom_id] = {
                    "status_code": None,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "retryable": retryable,
                    "opens_provider_circuit": opens_circuit,
                    "cost_accounted": bool(
                        getattr(exc, "batch_cost_accounted", False)
                    ),
                }
        state["observed_api_usd"] = self._spent_usd
        state["observed_by_model_usd"] = dict(
            sorted(self._spent_by_model.items())
        )
        retry_ids: set[str] = set()
        for custom_id, error in errors.items():
            status = error.get("status_code")
            value = RuntimeError(json.dumps(error, default=str))
            if isinstance(status, int):
                value.status_code = status  # type: ignore[attr-defined]
            retryable_value = error.get("retryable")
            circuit_value = error.get("opens_provider_circuit")
            if isinstance(retryable_value, bool) and isinstance(
                circuit_value, bool
            ):
                retryable, opens_circuit = retryable_value, circuit_value
            else:
                retryable, opens_circuit = _retry_disposition(value)
            if opens_circuit:
                self._circuit_open[self.config.models[0]] = str(value)
            if retryable and int(state["attempt"]) <= self.config.max_retries:
                retry_ids.add(custom_id)
            else:
                failures[custom_id] = error
        if retry_ids:
            entries = (
                self._batch_initial_entries(jobs, retry_ids)
                if phase == "initial"
                else self._batch_synthesis_entries(
                    jobs,
                    state["initial_results"],  # type: ignore[arg-type]
                    retry_ids,
                )
            )
            retry_reservations = {
                custom_id: (
                    self._request_cost(
                        self.config.models[0],
                        input_tokens,
                        self.config.max_output_tokens,
                        cache_write_input_tokens=(
                            self._cache_write_reservation_tokens(
                                self.config.models[0],
                                request,
                                input_tokens,
                            )
                        ),
                    )
                    or 0.0
                ) * 0.5
                for custom_id, request in entries
                for input_tokens in (
                    self.count_tokens(self.config.models[0], request),
                )
            }
            retry_reservation = sum(retry_reservations.values())
            previous_risk = state.get("unverified_failed_request_risk_usd", 0.0)
            risk = float(previous_risk) if isinstance(previous_risk, (int, float)) else 0.0
            risk += sum(
                reservation
                for custom_id, reservation in retry_reservations.items()
                if errors.get(custom_id, {}).get("cost_accounted") is not True
            )
            state["unverified_failed_request_risk_usd"] = risk
            self._unverified_failure_risk_usd = risk
            if (
                self.config.max_cost_usd is not None
                and self._spent_usd + risk + retry_reservation
                > self.config.max_cost_usd
            ):
                for custom_id in retry_ids:
                    failures[custom_id] = {
                        **errors[custom_id],
                        "retry_suppressed": "run cost budget",
                    }
                retry_ids.clear()
        if retry_ids:
            state["attempt"] = int(state["attempt"]) + 1
            self._submit_batch(client, state, entries)
            return 0
        if phase == "initial":
            synthesis_entries = self._batch_synthesis_entries(
                jobs, results  # type: ignore[arg-type]
            )
            if synthesis_entries:
                state.update({"phase": "synthesis", "attempt": 1})
                self._submit_batch(client, state, synthesis_entries)
                return 0
        state.update({"phase": "complete", "status": "completed"})
        write_json_atomic(state_path, state)
        return self._finish(self._batch_records(jobs, state), jobs)

    def _request_with_retries(
        self,
        model: str,
        request: StructuredRequest,
        *,
        input_tokens: int,
        base_url: str | None,
    ) -> tuple[GenerationResult, dict[str, object], int]:
        expected_request = request_parameters_for_model(
            model,
            base_url=base_url,
            max_output_tokens=self.config.max_output_tokens,
        )
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 2):
            try:
                generation = self._generate_budgeted(
                    model,
                    request,
                    input_tokens=input_tokens,
                    base_url=base_url,
                )
                if (
                    generation.requested_model != model
                    or generation.provider != expected_request["provider"]
                    or generation.request_parameters != expected_request
                ):
                    raise ValueError("detection generation provenance mismatch")
                verdict = _extract_model_output(
                    generation.text, self.config.detection
                )
                return generation, verdict, attempt
            except Exception as exc:
                last_error = exc
                retryable, opens_circuit = _retry_disposition(exc)
                if opens_circuit:
                    with self._budget_lock:
                        self._circuit_open[model] = str(exc)
                if not retryable or attempt > self.config.max_retries:
                    setattr(exc, "attempt_count", attempt)
                    setattr(exc, "retryable", retryable)
                    raise
        assert last_error is not None
        raise last_error

    def _one_with_retries(self, job: PreparedJob) -> dict[str, object]:
        try:
            return self._one(job)
        except Exception as exc:
            return {
                "case_id": job.case.case_id,
                "source_kind": job.source_kind,
                "source_path": str(job.case.path),
                "provider": job.model,
                "model": job.model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "attempt_count": getattr(exc, "attempt_count", 1),
                "max_retries": self.config.max_retries,
                "retry_exhausted": bool(getattr(exc, "retryable", False)),
            }

    def _one(self, job: PreparedJob) -> dict[str, object]:
        case, model, source_kind = job.case.path, job.model, job.source_kind
        case_id = job.case.case_id
        source_key = job.case.case_id
        root = self.config.output_dir / "cases" / source_key / model.replace("/", "_")
        verdict_path = root / "verdict.json"
        metadata_path = root / "metadata.json"
        prompts_path = root / "prompts.json"
        responses_path = root / "responses.json"
        generations_path = root / "generations.json"
        base_url = self.config.base_urls.get(model)
        expected_request = request_parameters_for_model(
            model,
            base_url=base_url,
            max_output_tokens=self.config.max_output_tokens,
        )
        request_hashes = [sha256_text(request.flat_prompt()) for request in job.requests]
        resume_identity = {
            "implementation_sha256": sha256_file(Path(__file__)),
            "evidence_index_sha256": index_implementation_sha256(),
            "run_provenance_sha256": self.run_provenance_sha256,
            "detection": self.config.detection,
            "requested_model": model,
            "request_sha256s": request_hashes,
            "input_tokens": list(job.input_tokens),
            "request_parameters": expected_request,
        }
        existing_metadata: dict[str, object] | None = None
        if metadata_path.is_file():
            try:
                value = json.loads(metadata_path.read_text(encoding="utf-8"))
                existing_metadata = value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                existing_metadata = None
        artifacts = (
            existing_metadata.get("artifacts")
            if existing_metadata is not None else None
        )
        artifact_paths = {
            "prompts_sha256": prompts_path,
            "responses_sha256": responses_path,
            "generations_sha256": generations_path,
            "verdict_sha256": verdict_path,
        }
        artifacts_current = (
            isinstance(artifacts, dict)
            and all(
                type(artifacts.get(name)) is str
                and path.is_file()
                and sha256_file(path) == artifacts[name]
                for name, path in artifact_paths.items()
            )
        )
        generation_current = False
        if generations_path.is_file() and existing_metadata is not None:
            try:
                generation_current = (
                    json.loads(generations_path.read_text(encoding="utf-8"))
                    == existing_metadata.get("generations")
                )
            except json.JSONDecodeError:
                generation_current = False
        current = (
            existing_metadata is not None
            and set(existing_metadata) == {
                "resume_identity", "compact_evidence", "attempt_count",
                "generations", "artifacts",
            }
            and existing_metadata.get("resume_identity") == resume_identity
            and existing_metadata.get("compact_evidence") == job.compact_stats
            and isinstance(existing_metadata.get("generations"), list)
            and artifacts_current
            and generation_current
        )
        if self.config.resume and verdict_path.is_file() and current:
            verdict_text = verdict_path.read_text(encoding="utf-8")
            verdict = (
                _validate_rh_verdict(json.loads(verdict_text))
                if self.config.detection == "rh"
                else _extract(verdict_text, self.config.detection)
            )
            status = "skipped"
            assert existing_metadata is not None
            generations = existing_metadata["generations"]
            assert isinstance(generations, list) and generations
            selected_generation = (
                int(verdict["selected_chunk"]) - 1
                if self.config.detection == "rh"
                else len(generations) - 1
            )
            generation_provenance = generations[selected_generation][
                "generation"
            ]
            attempt_count = int(existing_metadata.get("attempt_count", 0))
        else:
            if os.path.lexists(root):
                if not self.config.resume:
                    raise FileExistsError(f"model output exists: {root}; use --resume")
                if root.is_symlink() or not root.is_dir():
                    raise RuntimeError(
                        f"invalid reward-hacking model output directory: {root}"
                    )
                shutil.rmtree(root)
            root.mkdir(parents=True)
            requests = list(job.requests)
            token_counts = list(job.input_tokens)
            prompts: list[dict[str, object]] = []
            responses: list[dict[str, object]] = []
            generations: list[dict[str, object]] = []
            chunk_verdicts: list[dict[str, object]] = []
            attempt_count = 0
            for index, (request, input_tokens) in enumerate(
                zip(requests, token_counts, strict=True), start=1
            ):
                generation, chunk_verdict, attempts = self._request_with_retries(
                    model,
                    request,
                    input_tokens=input_tokens,
                    base_url=base_url,
                )
                attempt_count += attempts
                stage = job.request_stage
                prompts.append({"stage": stage, "index": index,
                                "input_tokens": input_tokens,
                                "prompt": request.flat_prompt()})
                responses.append({"stage": stage, "index": index,
                                  "text": generation.text})
                generations.append({"stage": stage, "index": index,
                                    "input_tokens": input_tokens,
                                    "generation": generation.provenance()})
                chunk_verdicts.append(chunk_verdict)
            if job.aggregation == "max_score":
                verdict = _aggregate_rh_scores(chunk_verdicts)
                selected = int(verdict["selected_chunk"]) - 1
                generation_provenance = generations[selected]["generation"]
            elif job.requires_synthesis:
                payload = self._payload(job.case)
                synthesis = _synthesis_request(
                    payload,
                    self.config.detection,
                    chunk_verdicts,
                    max_output_tokens=self.config.max_output_tokens,
                )
                synthesis_tokens = self.count_tokens(model, synthesis)
                if synthesis_tokens > self.config.max_input_tokens:
                    raise ValueError(
                        f"chunk synthesis requires {synthesis_tokens} tokens, above "
                        f"the {self.config.max_input_tokens} token ceiling"
                    )
                generation, verdict, attempts = self._request_with_retries(
                    model,
                    synthesis,
                    input_tokens=synthesis_tokens,
                    base_url=base_url,
                )
                attempt_count += attempts
                prompts.append({"stage": "synthesis", "index": 1,
                                "input_tokens": synthesis_tokens,
                                "prompt": synthesis.flat_prompt()})
                responses.append({"stage": "synthesis", "index": 1,
                                  "text": generation.text})
                generations.append({"stage": "synthesis", "index": 1,
                                    "input_tokens": synthesis_tokens,
                                    "generation": generation.provenance()})
                generation_provenance = generations[-1]["generation"]
            else:
                verdict = chunk_verdicts[0]
                generation_provenance = generations[0]["generation"]
            write_json_atomic(prompts_path, prompts)
            write_json_atomic(responses_path, responses)
            write_json_atomic(generations_path, generations)
            write_json_atomic(verdict_path, verdict)
            write_json_atomic(metadata_path, {
                "resume_identity": resume_identity,
                "compact_evidence": job.compact_stats,
                "attempt_count": attempt_count,
                "generations": generations,
                "artifacts": {
                    name: sha256_file(path)
                    for name, path in artifact_paths.items()
                },
            })
            status = "completed"
        return {"case_id": case_id, "source_kind": source_kind,
                "source_path": str(case), "provider": model, "model": model,
                "status": status, "compact_evidence": job.compact_stats,
                "generation": generation_provenance,
                "generations": generations,
                "attempt_count": attempt_count,
                "max_retries": self.config.max_retries,
                "retry_exhausted": False,
                "verdict": verdict}
