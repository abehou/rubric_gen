"""Execute and persist reward-hacking model-panel audits."""

from __future__ import annotations

import json
import shutil
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.evidence.index import index_implementation_sha256
from rubric_gen.reward_hacking.batch import BatchOutcome, OpenAIBatchRunner
from rubric_gen.reward_hacking.metrics import detection_rates, plot_detection_rates
from rubric_gen.reward_hacking.planning import plan_requests
from rubric_gen.reward_hacking.jobs import (
    PreparationFailure,
    PreparedJob,
    PreparedPanel,
    RewardHackingJudgeConfig,
)
from rubric_gen.reward_hacking.protocol import (
    ANTHROPIC_RH_EFFORT,
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
    EvidencePrompt,
    _retry_disposition,
)
from rubric_gen.reward_hacking.sources import AuditCase
from rubric_gen.reward_hacking.standard import StandardJobRunner, StandardOutcome
from rubric_gen.reward_hacking.targets import detection_target
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    count_input_tokens,
    estimate_input_tokens,
    generate_structured,
    generate_structured_vllm,
    request_parameters_for_model,
)
from rubric_gen.runtime.pricing import (
    HOSTED_PRICES_PER_MILLION,
    OPENAI_LONG_CONTEXT_THRESHOLD,
    OPENAI_LONG_INPUT_MULTIPLIER,
    OPENAI_LONG_OUTPUT_MULTIPLIER,
    PRICING_AS_OF,
    PRICING_SOURCES,
)
from rubric_gen.runtime.progress import TerminalProgress


def _implementation_sha256s() -> dict[str, str]:
    root = Path(__file__).parent
    return {
        name: sha256_file(root / name)
        for name in (
            "batch.py",
            "batch_state.py",
            "costs.py",
            "jobs.py",
            "metrics.py",
            "planning.py",
            "protocol.py",
            "review.py",
            "runner.py",
            "sources.py",
            "standard.py",
            "standard_state.py",
            "targets.py",
        )
    }


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
        self._spent_usd = 0.0
        self._spent_by_model: dict[str, float] = {}
        self._unverified_failure_risk_usd = 0.0
        self.run_provenance = {
            "implementation_sha256s": _implementation_sha256s(),
            "evidence_index_sha256": index_implementation_sha256(),
            "detection": config.detection,
            "detection_target": target.provenance(),
            "models": list(config.models),
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
        plan = plan_requests(
            detection=self.config.detection,
            case_id=case.case_id,
            model=model,
            payload=payload,
            max_input_tokens=self.config.max_input_tokens,
            max_output_tokens=self.config.max_output_tokens,
            count_tokens=self.count_tokens,
        )
        return PreparedJob(
            case=case,
            model=model,
            requests=plan.requests,
            input_tokens=plan.input_tokens,
            compact_stats={
                **payload.stats,
                **plan.stats,
            },
            aggregation=plan.aggregation,
        )

    def _prepare_jobs(self) -> PreparedPanel:
        cases = sorted(self.config.source.cases, key=lambda case: case.sort_key)
        total = len(cases) * len(self.config.models)
        jobs: list[PreparedJob] = []
        unavailable: dict[str, tuple[str, str]] = {}
        with TerminalProgress(
            total=total,
            description="Audit preparation",
            unit="job",
        ) as progress:
            for case in cases:
                progress.set_status(f"loading {case.case_id}")
                payload = (
                    self._payload(case)
                    if len(unavailable) < len(self.config.models)
                    else None
                )
                for model in self.config.models:
                    if model in unavailable:
                        progress.set_status(
                            f"skipping {case.case_id} for unavailable {model}"
                        )
                        progress.update()
                        continue
                    assert payload is not None
                    progress.set_status(f"planning {case.case_id} for {model}")
                    try:
                        jobs.append(self._prepare_job(case, model, payload))
                    except Exception as exc:
                        _retryable, opens_circuit = _retry_disposition(exc)
                        if not opens_circuit:
                            raise
                        unavailable[model] = (type(exc).__name__, str(exc))
                        jobs = [job for job in jobs if job.model != model]
                    progress.update()
        failures = tuple(
            PreparationFailure(
                case=case,
                model=model,
                error_type=unavailable[model][0],
                error=unavailable[model][1],
            )
            for case in cases
            for model in self.config.models
            if model in unavailable
        )
        return PreparedPanel(jobs=tuple(jobs), failures=failures)

    def run(self) -> int:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        standard = self._standard_runner()
        try:
            self._write_or_validate_run_provenance()
            if standard is not None:
                standard.initialize_cost_state()
        except ValueError:
            if not self.config.resume:
                raise
            self._replace_incompatible_output()
            self.config = replace(self.config, resume=False)
            standard = self._standard_runner()
            self._write_or_validate_run_provenance()
            if standard is not None:
                standard.initialize_cost_state()
        prepared = self._prepare_jobs()
        jobs = prepared.jobs
        preparation_failures = [
            failure.record(self.config.max_retries)
            for failure in prepared.failures
        ]
        if self.config.execution == "batch":
            if preparation_failures:
                return self._finish(preparation_failures)
            outcome = OpenAIBatchRunner(
                self.config,
                jobs,
                self.run_provenance_sha256,
                self.count_tokens,
                self._payload,
            ).run()
            self._set_costs(outcome)
            return 0 if outcome.records is None else self._finish(outcome.records)
        if standard is None:
            raise AssertionError("standard execution has no standard runner")
        records = self._run_standard(standard, jobs, preparation_failures)
        self._set_costs(standard.outcome)
        return self._finish(records)

    def _standard_runner(self) -> StandardJobRunner | None:
        if self.config.execution != "standard":
            return None
        return StandardJobRunner(
            self.config,
            self.run_provenance_sha256,
            _implementation_sha256s(),
            self.generate_response,
            self.generate_vllm_response,
            self.count_tokens,
            self._payload,
        )

    def _set_costs(self, outcome: StandardOutcome | BatchOutcome) -> None:
        self._spent_usd = outcome.observed_api_usd
        self._spent_by_model = outcome.observed_by_model_usd
        self._unverified_failure_risk_usd = (
            outcome.unverified_failed_request_risk_usd
        )

    def _run_standard(
        self,
        standard: StandardJobRunner,
        jobs: tuple[PreparedJob, ...],
        preparation_failures: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        records = preparation_failures
        with TerminalProgress(
            total=len(jobs), description="Reward-hacking model panel", unit="judgment"
        ) as progress:
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                grouped: dict[tuple[str, str], deque[PreparedJob]] = {}
                for job in jobs:
                    grouped.setdefault(
                        standard.cache_group(job), deque()
                    ).append(job)
                pending = deque(grouped.values())
                active: dict[
                    Future[dict[str, object]],
                    tuple[deque[PreparedJob], PreparedJob],
                ] = {}

                def submit_next(group: deque[PreparedJob]) -> None:
                    job = group.popleft()
                    active[pool.submit(standard.execute, job)] = (group, job)

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
        return records

    def _replace_incompatible_output(self) -> None:
        root = self.config.output_dir
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(f"invalid reward-hacking output directory: {root}")
        shutil.rmtree(root)
        root.mkdir(parents=True)

    def _finish(self, records: list[dict[str, object]]) -> int:
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
