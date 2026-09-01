"""Execute and persist behavior-detection panels."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.evidence.index import index_implementation_sha256
from rubric_gen.detection.metrics import detection_rates, plot_detection_rates
from rubric_gen.detection.planning import plan_requests
from rubric_gen.detection.jobs import (
    JUDGE_MAX_ATTEMPTS,
    PreparationFailure,
    PreparedJob,
    PreparedPanel,
    DetectionConfig,
)
from rubric_gen.detection.config import (
    ANTHROPIC_EFFORT,
    GEMINI_THINKING_LEVEL,
    MALT_REWARD_HACKING_AGGREGATION,
    MALT_REWARD_HACKING_CHARS_PER_TOKEN,
    MALT_REWARD_HACKING_DECISION_RULE,
    MALT_REWARD_HACKING_MAX_INPUT_TOKENS,
    MALT_REWARD_HACKING_SOURCE,
    OPENAI_REASONING_EFFORT,
    OPENAI_TEXT_VERBOSITY,
    INPUT_VALIDATION_POLICY,
    PROMPT_CACHE_POLICY,
)
from rubric_gen.detection.prompts import EvidencePrompt
from rubric_gen.detection.sources import AuditCase
from rubric_gen.detection.job_runner import DetectionJobRunner, DetectionOutcome
from rubric_gen.detection.targets import detection_target
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    count_input_tokens,
    estimate_input_tokens,
    generate_structured,
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


def scoring_implementation_sha256() -> str:
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in (
            "costs.py",
            "jobs.py",
            "metrics.py",
            "planning.py",
            "config.py",
            "prompts.py",
            "runner.py",
            "sources.py",
            "job_runner.py",
            "targets.py",
    ):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    digest.update(index_implementation_sha256().encode("ascii"))
    return digest.hexdigest()


class DetectionRunner:
    def __init__(
        self, config: DetectionConfig,
        *, generate_response: Callable[[str, StructuredRequest], GenerationResult] = generate_structured,
        count_tokens: Callable[[str, StructuredRequest], int] | None = None,
    ) -> None:
        self.config = config
        target = detection_target(config.detection)
        self.generate_response = generate_response
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
        self.run_settings = {
            "scoring_implementation_sha256": scoring_implementation_sha256(),
            "detection": config.detection,
            "detection_target": target.provenance(),
            "models": list(config.models),
            "max_attempts": JUDGE_MAX_ATTEMPTS,
            "max_input_tokens": config.max_input_tokens,
            "max_output_tokens": config.max_output_tokens,
            "primary_rule": config.primary_rule,
            "source": config.source.provenance,
            "openai_reasoning_effort": OPENAI_REASONING_EFFORT,
            "openai_text_verbosity": OPENAI_TEXT_VERBOSITY,
            "anthropic_effort": ANTHROPIC_EFFORT,
            "gemini_thinking_level": GEMINI_THINKING_LEVEL,
            "prompt_cache": PROMPT_CACHE_POLICY,
            "input_validation": INPUT_VALIDATION_POLICY,
            "reward_hacking_monitor": (
                {
                    "source": MALT_REWARD_HACKING_SOURCE,
                    "shared_context": "original_task_context",
                    "behavior_chunking": "all_messages_in_source_order",
                    "field_text": "complete",
                    "overflow": "fail_without_fallback",
                    "chunk_max_input_tokens": MALT_REWARD_HACKING_MAX_INPUT_TOKENS,
                    "chars_per_token": MALT_REWARD_HACKING_CHARS_PER_TOKEN,
                    "aggregation": MALT_REWARD_HACKING_AGGREGATION,
                    "derived_decision_rule": MALT_REWARD_HACKING_DECISION_RULE,
                }
                if config.detection == "rh"
                else None
            ),
            "model_requests": {
                model: request_parameters_for_model(
                    model,
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
    def _write_or_validate_run_settings(self) -> None:
        path = self.config.output_dir / "run.json"
        expected = self.run_settings
        if path.is_file():
            if not self.config.resume:
                raise FileExistsError(f"reward-hacking run already exists: {path}")
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid run settings: {path}") from exc
            if existing != expected:
                raise ValueError(
                    "existing run settings do not exactly match the requested run"
                )
            return
        if self.config.resume:
            raise ValueError("resumed run has no run.json")
        write_json_atomic(path, expected)

    def _payload(self, case: AuditCase) -> EvidencePrompt:
        return self.config.source.prompt(case, self.config.detection)

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
        jobs: list[PreparedJob | None] = [None] * total
        failures: list[PreparationFailure | None] = [None] * total
        with TerminalProgress(
            total=total,
            description="Audit preparation",
            unit="job",
        ) as progress:
            with ThreadPoolExecutor(
                max_workers=self.config.max_concurrency
            ) as pool:
                pending: dict[
                    Future[PreparedJob], tuple[int, AuditCase, str]
                ] = {}
                index = 0
                for case in cases:
                    progress.set_status(f"loading {case.case_id}")
                    payload = self._payload(case)
                    for model in self.config.models:
                        progress.set_status(f"planning {case.case_id} for {model}")
                        future = pool.submit(
                            self._prepare_job,
                            case,
                            model,
                            payload,
                        )
                        pending[future] = (index, case, model)
                        index += 1
                remaining = set(pending)
                while remaining:
                    done, remaining = wait(
                        remaining,
                        return_when=FIRST_COMPLETED,
                    )
                    for future in done:
                        job_index, case, model = pending[future]
                        try:
                            jobs[job_index] = future.result()
                        except Exception as exc:
                            failures[job_index] = PreparationFailure(
                                case=case,
                                model=model,
                                error_type=type(exc).__name__,
                                error=str(exc),
                            )
                        progress.update()
        return PreparedPanel(
            jobs=tuple(job for job in jobs if job is not None),
            failures=tuple(failure for failure in failures if failure is not None),
        )

    def run(self) -> int:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_or_validate_run_settings()
        standard = self._standard_runner()
        prepared = self._prepare_jobs()
        jobs = prepared.jobs
        preparation_failures = [
            failure.record()
            for failure in prepared.failures
        ]
        records = self._run_standard(standard, jobs, preparation_failures)
        self._set_costs(standard.outcome)
        return self._finish(records)

    def _standard_runner(self) -> DetectionJobRunner:
        return DetectionJobRunner(
            self.config,
            self.run_settings,
            self.generate_response,
            self.count_tokens,
            self._payload,
        )

    def _set_costs(self, outcome: DetectionOutcome) -> None:
        self._spent_usd = outcome.observed_api_usd
        self._spent_by_model = outcome.observed_by_model_usd

    def _run_standard(
        self,
        standard: DetectionJobRunner,
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
                            records.append({
                                "case_id": job.case.case_id,
                                "source_kind": job.source_kind,
                                "source_path": str(job.case.path),
                                "provider": job.model,
                                "model": job.model,
                                "status": "failed",
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                            })
                        progress.update()
                        if group:
                            submit_next(group)
                        elif pending:
                            submit_next(pending.popleft())
        return records

    def _finish(self, records: list[dict[str, object]]) -> int:
        records.sort(key=lambda row: (str(row["case_id"]), str(row["model"])))
        summary = {
            "kind": "reward-hacking-model-panel",
            "models": list(self.config.models),
            "max_attempts": JUDGE_MAX_ATTEMPTS,
            "detection": self.config.detection,
            "detection_target": detection_target(
                self.config.detection
            ).provenance(),
            "primary_rule": self.config.primary_rule,
            "reward_hacking_monitor": self.run_settings.get("reward_hacking_monitor"),
            "source": self.config.source.provenance,
            "run_settings": self.run_settings,
            "cost": {
                "observed_api_usd": self._spent_usd,
                "observed_by_model_usd": dict(
                    sorted(self._spent_by_model.items())
                ),
                "pricing_sources": PRICING_SOURCES,
                "pricing_as_of": PRICING_AS_OF,
            },
            "records": records,
        }
        write_json_atomic(self.config.output_dir / "summary.json", summary)
        successful = sum(
            row["status"] in {"completed", "skipped"} for row in records
        )
        if successful == 0:
            return 1
        rates = detection_rates(summary)
        rates["completed_results"] = successful
        rates["missing_results"] = len(records) - successful
        write_json_atomic(self.config.output_dir / "detection-rates.json", rates)
        plot_detection_rates(rates, self.config.output_dir / "detection-rates.png")
        return 0
