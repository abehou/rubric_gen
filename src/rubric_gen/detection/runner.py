"""Execute and persist behavior-detection panels."""

from __future__ import annotations

from rubric_gen.runtime.capacity import limited

import hashlib
import json
import time
from collections import deque
from contextlib import nullcontext
from threading import Lock
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


def scoring_implementation_sha256(source_root: Path | None = None) -> str:
    root = source_root / "src/rubric_gen/detection" if source_root else Path(__file__).parent
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
    for name in ("llm.py", "integrations/gemini.py"):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root.parent / "runtime" / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class DetectionRunner:
    def __init__(
        self, config: DetectionConfig,
        *, generate_response: Callable[[str, StructuredRequest], GenerationResult] = generate_structured,
        count_tokens: Callable[[str, StructuredRequest], int] | None = None,
        resume_code_root: Path | None = None,
    ) -> None:
        self.config = config
        self.resume_code_root = resume_code_root
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
        self._payloads = {}
        self._payload_locks = {}
        self._payload_lock = Lock()
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
                compared = {k: v for k, v in expected.items() if k != 'scoring_implementation_sha256'}
                saved = {k: v for k, v in existing.items() if k != 'scoring_implementation_sha256'}
                origin = self.resume_code_root
                if compared != saved or origin is None or scoring_implementation_sha256(origin) != existing.get('scoring_implementation_sha256'):
                    raise ValueError("existing run settings do not exactly match the requested run")
                # The original deployment must still supply its exact recorded
                # implementation. Only execution/publication owners changed;
                # all request, prompt, chunk, parsing and aggregation modules
                # must remain byte-identical. Preserve the original run record.
                current = Path(__file__).parents[3]
                scientific = ('detection/costs.py', 'detection/jobs.py', 'detection/metrics.py',
                              'detection/planning.py', 'detection/config.py', 'detection/prompts.py',
                              'detection/sources.py', 'detection/targets.py', 'runtime/llm.py',
                              'runtime/integrations/gemini.py')
                for name in scientific:
                    relative = Path('src/rubric_gen') / name
                    if (origin / relative).read_bytes() != (current / relative).read_bytes():
                        raise ValueError(f"direct resume scientific implementation changed: {name}")
                self.run_settings = existing
            return
        if self.config.resume:
            raise ValueError("resumed run has no run.json")
        write_json_atomic(path, expected)

    def _payload(self, case: AuditCase) -> EvidencePrompt:
        return self.config.source.prompt(case, self.config.detection)

    def _count_preparation_tokens(self, model: str, request: StructuredRequest) -> int:
        from rubric_gen.runtime.failures import failure_category, retry_after
        from rubric_gen.runtime.capacity import emit

        for attempt in range(3):
            try:
                return self.count_tokens(model, request)
            except Exception as error:
                if not failure_category(error).startswith('transient_') or attempt == 2:
                    raise
                delay = retry_after(error, attempt + 1)
                emit('retry_wait', operation='token-count', category=failure_category(error), wait_seconds=delay)
                time.sleep(delay)
        raise AssertionError("unreachable token-count retry state")

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
            count_tokens=self._count_preparation_tokens,
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

    def _prepare_source_job(self, case, model):
        from rubric_gen.runtime.capacity import emit
        started = time.monotonic()
        with self._payload_lock:
            lock = self._payload_locks.setdefault(case.path, Lock())
        with lock:
            if case.path not in self._payloads:
                self._payloads[case.path] = self._payload(case)
            payload = self._payloads[case.path]
        loaded = time.monotonic()
        job = self._prepare_job(case, model, payload)
        emit("audit_prepared", case_id=case.case_id, model=model,
             source_seconds=loaded-started, plan_seconds=time.monotonic()-loaded)
        return job

    def _prepare_jobs(self) -> PreparedPanel:
        # Keep the standalone planning interface bounded as well as the pipeline.
        jobs, failures = [], []
        work = iter((case, model) for case in sorted(self.config.source.cases, key=lambda c: c.sort_key)
                    for model in self.config.models)
        with TerminalProgress(total=len(self.config.source.cases)*len(self.config.models),
                              description="Audit source loading and planning", unit="job") as progress:
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                active = {}
                def refill():
                    while len(active) < self.config.max_concurrency:
                        item = next(work, None)
                        if item is None:
                            break
                        active[pool.submit(self._prepare_source_job, *item)] = item
                refill()
                while active:
                    done, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in done:
                        case, model = active.pop(future)
                        try:
                            jobs.append(future.result())
                        except Exception as exc:
                            failures.append(PreparationFailure(case, model, type(exc).__name__, str(exc)))
                        progress.set_status(f"prepared {case.case_id} for {model}")
                        progress.update()
                    refill()
        jobs.sort(key=lambda job: (job.case.sort_key, self.config.models.index(job.model)))
        failures.sort(key=lambda job: (job.case.sort_key, self.config.models.index(job.model)))
        return PreparedPanel(tuple(jobs), tuple(failures))

    def _run_pipeline(self, standard, executor):
        """Feed ready requests while other sources are loading, within one pool."""
        work = iter((case, model) for case in sorted(self.config.source.cases, key=lambda c: c.sort_key)
                    for model in self.config.models)
        active, ready, groups, records = {}, deque(), set(), []
        exhausted = False
        def refill():
            nonlocal exhausted
            for _ in range(len(ready)):
                job = ready.popleft()
                group = standard.cache_group(job)
                if len(active) < self.config.max_concurrency and group not in groups:
                    groups.add(group)
                    active[executor.submit(standard.execute, job)] = ('generation', job)
                else:
                    ready.append(job)
            while not exhausted and len(active) + len(ready) < self.config.max_concurrency:
                item = next(work, None)
                if item is None:
                    exhausted = True
                    break
                case, model = item
                active[executor.submit(self._prepare_source_job, case, model, model=model)] = ('prepare', item)
        with TerminalProgress(total=len(self.config.source.cases)*len(self.config.models),
                              description="Audit source/plan/generation", unit="judgment") as progress:
            refill()
            while active or ready:
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    phase, item = active.pop(future)
                    if phase == 'generation':
                        groups.remove(standard.cache_group(item))
                    try:
                        value = future.result()
                        if phase == 'prepare':
                            ready.append(value)
                        else:
                            records.append(value)
                            progress.update()
                    except Exception as exc:
                        case, model = item if phase == 'prepare' else (item.case, item.model)
                        records.append(PreparationFailure(case, model, type(exc).__name__, str(exc)).record())
                        progress.update()
                    progress.set_status(f"{phase}: {len(active)} active, {len(ready)} ready")
                refill()
        return records

    @limited("audit-stage", kind="audit", returns_exit_code=True)
    def run(self) -> int:
        return self.run_prepared()

    def run_prepared(self, prepared=None, executor=None) -> int:
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_or_validate_run_settings()
        standard = self._standard_runner()
        if prepared is None:
            from rubric_gen.runtime.audit_execution import AuditExecutor
            with (nullcontext(executor) if executor is not None else
                  AuditExecutor(self.config.max_concurrency, self.config.models)) as pool:
                records = self._run_pipeline(standard, pool)
        else:
            records = self._run_standard(standard, prepared.jobs,
                                        [f.record() for f in prepared.failures], executor)
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
        executor=None,
    ) -> list[dict[str, object]]:
        records = preparation_failures
        with TerminalProgress(
            total=len(jobs), description="Reward-hacking model panel", unit="judgment"
        ) as progress:
            with (nullcontext(executor) if executor is not None else
                  ThreadPoolExecutor(max_workers=self.config.max_concurrency)) as pool:
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
        return int(successful != len(records))
