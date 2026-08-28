"""Execute OpenAI Batch reward-hacking audits."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO, Callable, Protocol

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.reward_hacking.batch_state import (
    BatchState,
    BatchSubmission,
    JsonObject,
)
from rubric_gen.reward_hacking.costs import (
    cache_write_reservation_tokens,
    request_cost,
    usage_tokens,
)
from rubric_gen.reward_hacking.jobs import PreparedJob, RewardHackingJudgeConfig
from rubric_gen.reward_hacking.protocol import OPENAI_RH_REASONING_EFFORT
from rubric_gen.reward_hacking.review import (
    EvidencePrompt,
    _aggregate_rh_scores,
    _extract_model_output,
    _retry_disposition,
    _synthesis_request,
)
from rubric_gen.reward_hacking.sources import AuditCase
from rubric_gen.runtime.llm import (
    GenerationResult,
    HOSTED_REQUEST_TIMEOUT_SECONDS,
    StructuredRequest,
    metadata_value,
    openai_prompt_cache_arguments,
    request_parameters_for_model,
)


class _UploadedFile(Protocol):
    id: str


class _RemoteBatch(Protocol):
    id: str
    status: str
    output_file_id: str | None
    error_file_id: str | None


class _FilesAPI(Protocol):
    def create(self, *, file: BinaryIO, purpose: str) -> _UploadedFile: ...

    def content(self, file_id: str) -> object: ...


class _BatchesAPI(Protocol):
    def create(
        self,
        *,
        input_file_id: str,
        endpoint: str,
        completion_window: str,
        metadata: dict[str, str],
    ) -> _RemoteBatch: ...

    def retrieve(self, batch_id: str) -> _RemoteBatch: ...


class _OpenAIClient(Protocol):
    files: _FilesAPI
    batches: _BatchesAPI


class _BatchRequestError(RuntimeError):
    def __init__(self, message: str, status_code: int | None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class BatchOutcome:
    records: list[JsonObject] | None
    observed_api_usd: float
    observed_by_model_usd: dict[str, float]
    unverified_failed_request_risk_usd: float


@dataclass(frozen=True)
class _SelectedJobResult:
    result: JsonObject
    verdict: JsonObject
    request_ids: tuple[str, ...]
    initial_results: tuple[JsonObject, ...]


class OpenAIBatchRunner:
    def __init__(
        self,
        config: RewardHackingJudgeConfig,
        jobs: tuple[PreparedJob, ...],
        run_provenance_sha256: str,
        count_tokens: Callable[[str, StructuredRequest], int],
        load_payload: Callable[[AuditCase], EvidencePrompt],
    ) -> None:
        self.config = config
        self.jobs = jobs
        self.run_provenance_sha256 = run_provenance_sha256
        self.count_tokens = count_tokens
        self.load_payload = load_payload
        self._spent_usd = 0.0
        self._spent_by_model: dict[str, float] = {}
        self._unverified_failure_risk_usd = 0.0

    @property
    def observed_api_usd(self) -> float:
        return self._spent_usd

    def _outcome(self, records: list[JsonObject] | None = None) -> BatchOutcome:
        return BatchOutcome(
            records=records,
            observed_api_usd=self._spent_usd,
            observed_by_model_usd=dict(self._spent_by_model),
            unverified_failed_request_risk_usd=(
                self._unverified_failure_risk_usd
            ),
        )

    def _payload(self, case: AuditCase) -> EvidencePrompt:
        return self.load_payload(case)

    def _batch_body(
        self, model: str, request: StructuredRequest
    ) -> JsonObject:
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
    def _response_body_text(body: JsonObject) -> str:
        output = body.get("output")
        if not isinstance(output, list):
            raise RuntimeError("OpenAI Batch response contained no output list")
        pieces = [
            text
            for item in output
            if isinstance(item, dict) and item.get("type") == "message"
            for content in (item.get("content"),)
            if isinstance(content, list)
            for block in content
            if isinstance(block, dict) and block.get("type") == "output_text"
            for text in (block.get("text"),)
            if isinstance(text, str)
        ]
        result = "\n".join(pieces)
        if not result.strip():
            raise RuntimeError("OpenAI Batch response contained no output text")
        return result

    def _generation_from_batch(
        self, model: str, body: JsonObject
    ) -> GenerationResult:
        effective_model = body.get("model")
        response_id = body.get("id")
        if type(effective_model) is not str or type(response_id) is not str:
            raise RuntimeError("OpenAI Batch response omitted model identity")
        return GenerationResult(
            text=self._response_body_text(body),
            provider="openai",
            requested_model=model,
            effective_model=effective_model,
            response_id=response_id,
            request_parameters=request_parameters_for_model(
                model,
                max_output_tokens=self.config.max_output_tokens,
            ),
            provider_metadata={
                "batch": True,
                "created_at": metadata_value(body.get("created_at")),
                "service_tier": metadata_value(body.get("service_tier")),
                "usage": metadata_value(body.get("usage")),
            },
        )

    @staticmethod
    def _download_text(client: _OpenAIClient, file_id: str) -> str:
        content = client.files.content(file_id)
        text_value = getattr(content, "text", None)
        if isinstance(text_value, str):
            return text_value
        read = getattr(content, "read", None)
        value = read() if callable(read) else content
        return value.decode() if isinstance(value, bytes) else str(value)

    def _submit_batch(
        self,
        client: _OpenAIClient,
        state: BatchState,
        entries: list[tuple[str, StructuredRequest]],
    ) -> None:
        path = self.config.output_dir / (
            f"batch-{state.phase}-{state.attempt:02d}.jsonl"
        )
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
            uploaded = client.files.create(file=stream, purpose="batch")
        batch = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/responses",
            completion_window="24h",
            metadata={
                "kind": "reward-hacking-forensic-evaluation",
                "run": self.run_provenance_sha256[:32],
                "phase": state.phase,
            },
        )
        state.submission = BatchSubmission(
            status=batch.status,
            batch_id=batch.id,
            input_file_id=uploaded.id,
            custom_ids=tuple(custom_id for custom_id, _ in entries),
            local_input=path.name,
        )
        state.publish(self.config.output_dir / "batch-state.json")
        print(
            f"Submitted OpenAI Batch {batch.id} "
            f"({state.phase}, {len(entries)} requests). "
            "Rerun the identical command with --resume to collect it."
        )

    @staticmethod
    def _initial_entries(
        jobs: tuple[PreparedJob, ...],
        custom_ids: set[str] | None = None,
    ) -> list[tuple[str, StructuredRequest]]:
        entries = [
            (f"j{job_index:05d}-r{request_index:03d}", request)
            for job_index, job in enumerate(jobs)
            for request_index, request in enumerate(job.requests)
        ]
        if custom_ids is None:
            return entries
        return [entry for entry in entries if entry[0] in custom_ids]

    @staticmethod
    def _valid_result(value: object) -> JsonObject | None:
        if (
            not isinstance(value, dict)
            or set(value) != {"custom_id", "text", "generation", "verdict"}
            or type(value.get("custom_id")) is not str
            or type(value.get("text")) is not str
            or not isinstance(value.get("generation"), dict)
            or not isinstance(value.get("verdict"), dict)
        ):
            return None
        return value

    def synthesis_entries(
        self,
        jobs: tuple[PreparedJob, ...],
        initial_results: dict[str, JsonObject],
        custom_ids: set[str] | None = None,
    ) -> list[tuple[str, StructuredRequest]]:
        entries = [
            entry
            for job_index, job in enumerate(jobs)
            for entry in self._synthesis_entry(job_index, job, initial_results)
        ]
        if custom_ids is None:
            return entries
        return [entry for entry in entries if entry[0] in custom_ids]

    def _synthesis_entry(
        self,
        job_index: int,
        job: PreparedJob,
        initial_results: dict[str, JsonObject],
    ) -> tuple[tuple[str, StructuredRequest], ...]:
        if not job.requires_synthesis:
            return ()
        results = tuple(
            self._valid_result(
                initial_results.get(f"j{job_index:05d}-r{index:03d}")
            )
            for index in range(len(job.requests))
        )
        if any(result is None for result in results):
            return ()
        verdicts = [result["verdict"] for result in results if result is not None]
        request = _synthesis_request(
            self._payload(job.case),
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
        return ((f"j{job_index:05d}-s000", request),)

    @staticmethod
    def _parse_output_rows(
        text: str,
    ) -> tuple[dict[str, JsonObject], dict[str, JsonObject]]:
        outputs: dict[str, JsonObject] = {}
        errors: dict[str, JsonObject] = {}
        for line in text.splitlines():
            row = json.loads(line)
            custom_id = row.get("custom_id") if isinstance(row, dict) else None
            response = row.get("response") if isinstance(row, dict) else None
            if type(custom_id) is not str or not isinstance(response, dict):
                raise ValueError("OpenAI Batch output row has invalid structure")
            body = response.get("body")
            if response.get("status_code") == 200 and isinstance(body, dict):
                outputs[custom_id] = body
            else:
                errors[custom_id] = {
                    "status_code": response.get("status_code"),
                    "error": body,
                }
        return outputs, errors

    @staticmethod
    def _parse_error_rows(text: str) -> dict[str, JsonObject]:
        errors: dict[str, JsonObject] = {}
        for line in text.splitlines():
            row = json.loads(line)
            custom_id = row.get("custom_id") if isinstance(row, dict) else None
            if type(custom_id) is not str:
                raise ValueError("OpenAI Batch error row has invalid structure")
            errors[custom_id] = {
                "status_code": None,
                "error": row.get("error"),
            }
        return errors

    def _collect_batch_files(
        self,
        client: _OpenAIClient,
        batch: _RemoteBatch,
    ) -> tuple[dict[str, JsonObject], dict[str, JsonObject]]:
        outputs: dict[str, JsonObject] = {}
        errors: dict[str, JsonObject] = {}
        if isinstance(batch.output_file_id, str):
            text = self._download_text(client, batch.output_file_id)
            (self.config.output_dir / f"{batch.id}-output.jsonl").write_text(
                text,
                encoding="utf-8",
            )
            outputs, errors = self._parse_output_rows(text)
        if isinstance(batch.error_file_id, str):
            text = self._download_text(client, batch.error_file_id)
            (self.config.output_dir / f"{batch.id}-errors.jsonl").write_text(
                text,
                encoding="utf-8",
            )
            errors.update(self._parse_error_rows(text))
        return outputs, errors

    def parse_response(self, custom_id: str, body: JsonObject) -> JsonObject:
        generation = self._generation_from_batch(self.config.models[0], body)
        usage = usage_tokens(generation)
        if usage is not None:
            model = self.config.models[0]
            cost = (request_cost(model, **usage) or 0.0) * 0.5
            self._spent_usd += cost
            self._spent_by_model[model] = (
                self._spent_by_model.get(model, 0.0) + cost
            )
        try:
            verdict = _extract_model_output(
                generation.text,
                self.config.detection,
            )
        except Exception as exc:
            setattr(exc, "batch_cost_accounted", usage is not None)
            raise
        return {
            "custom_id": custom_id,
            "text": generation.text,
            "generation": generation.provenance(),
            "verdict": verdict,
        }

    @staticmethod
    def _request_ids(job_index: int, job: PreparedJob) -> tuple[str, ...]:
        return tuple(
            f"j{job_index:05d}-r{index:03d}"
            for index in range(len(job.requests))
        )

    def _select_job_result(
        self,
        job_index: int,
        job: PreparedJob,
        state: BatchState,
    ) -> _SelectedJobResult | None:
        request_ids = self._request_ids(job_index, job)
        initial = tuple(
            self._valid_result(state.initial_results.get(custom_id))
            for custom_id in request_ids
        )
        if any(result is None for result in initial):
            return None
        complete = tuple(result for result in initial if result is not None)
        if job.aggregation == "max_score":
            verdict = _aggregate_rh_scores([
                result["verdict"] for result in complete
            ])
            selected = complete[int(verdict["selected_chunk"]) - 1]
            return _SelectedJobResult(selected, verdict, request_ids, complete)
        if job.requires_synthesis:
            result = self._valid_result(
                state.synthesis_results.get(f"j{job_index:05d}-s000")
            )
            if result is None:
                return None
            return _SelectedJobResult(
                result,
                result["verdict"],
                request_ids,
                complete,
            )
        result = complete[0]
        return _SelectedJobResult(
            result,
            result["verdict"],
            request_ids,
            complete,
        )

    def _failure_record(
        self,
        job_index: int,
        job: PreparedJob,
        state: BatchState,
    ) -> JsonObject:
        request_ids = self._request_ids(job_index, job)
        relevant_ids = (
            (*request_ids, f"j{job_index:05d}-s000")
            if job.requires_synthesis
            else request_ids
        )
        failures = {**state.initial_failures, **state.synthesis_failures}
        error = next(
            (failures[custom_id] for custom_id in relevant_ids if custom_id in failures),
            {},
        )
        return {
            "case_id": job.case.case_id,
            "source_kind": job.source_kind,
            "source_path": str(job.case.path),
            "provider": job.model,
            "model": job.model,
            "status": "failed",
            "error_type": "BatchRequestError",
            "error": json.dumps(error, default=str),
            "attempt_count": state.attempt,
            "max_retries": self.config.max_retries,
            "retry_exhausted": False,
        }

    def _artifact_entries(
        self,
        job: PreparedJob,
        selected: _SelectedJobResult,
    ) -> tuple[list[JsonObject], list[JsonObject], list[JsonObject]]:
        prompts = [
            {
                "stage": job.request_stage,
                "index": index + 1,
                "input_tokens": job.input_tokens[index],
                "prompt": job.requests[index].flat_prompt(),
            }
            for index in range(len(job.requests))
        ]
        responses = [
            {
                "stage": job.request_stage,
                "index": index + 1,
                "text": result["text"],
            }
            for index, result in enumerate(selected.initial_results)
        ]
        generations = [
            {
                "stage": job.request_stage,
                "index": index + 1,
                "input_tokens": job.input_tokens[index],
                "generation": result["generation"],
            }
            for index, result in enumerate(selected.initial_results)
        ]
        if job.requires_synthesis:
            self._append_synthesis_artifacts(
                job,
                selected,
                prompts,
                responses,
                generations,
            )
        return prompts, responses, generations

    def _append_synthesis_artifacts(
        self,
        job: PreparedJob,
        selected: _SelectedJobResult,
        prompts: list[JsonObject],
        responses: list[JsonObject],
        generations: list[JsonObject],
    ) -> None:
        request = _synthesis_request(
            self._payload(job.case),
            self.config.detection,
            [result["verdict"] for result in selected.initial_results],
            max_output_tokens=self.config.max_output_tokens,
        )
        tokens = self.count_tokens(job.model, request)
        prompts.append({
            "stage": "synthesis",
            "index": 1,
            "input_tokens": tokens,
            "prompt": request.flat_prompt(),
        })
        responses.append({
            "stage": "synthesis",
            "index": 1,
            "text": selected.result["text"],
        })
        generations.append({
            "stage": "synthesis",
            "index": 1,
            "input_tokens": tokens,
            "generation": selected.result["generation"],
        })

    def _completed_record(
        self,
        job: PreparedJob,
        state: BatchState,
        selected: _SelectedJobResult,
    ) -> JsonObject:
        prompts, responses, generations = self._artifact_entries(job, selected)
        root = (
            self.config.output_dir
            / "cases"
            / job.case.case_id
            / job.model.replace("/", "_")
        )
        root.mkdir(parents=True, exist_ok=True)
        artifacts = {
            "prompts.json": prompts,
            "responses.json": responses,
            "generations.json": generations,
            "verdict.json": selected.verdict,
        }
        for filename, value in artifacts.items():
            write_json_atomic(root / filename, value)
        write_json_atomic(root / "metadata.json", {
            "execution": "batch",
            "compact_evidence": job.compact_stats,
            "attempt_count": state.attempt,
            "generations": generations,
            "artifacts": {
                filename.removesuffix(".json") + "_sha256": sha256_file(
                    root / filename
                )
                for filename in artifacts
            },
        })
        return {
            "case_id": job.case.case_id,
            "source_kind": job.source_kind,
            "source_path": str(job.case.path),
            "provider": job.model,
            "model": job.model,
            "status": "completed",
            "compact_evidence": job.compact_stats,
            "generation": selected.result["generation"],
            "generations": generations,
            "attempt_count": state.attempt,
            "max_retries": self.config.max_retries,
            "retry_exhausted": False,
            "verdict": selected.verdict,
        }

    def records_from_state(
        self,
        jobs: tuple[PreparedJob, ...],
        state: BatchState,
    ) -> list[JsonObject]:
        records: list[JsonObject] = []
        for job_index, job in enumerate(jobs):
            selected = self._select_job_result(job_index, job, state)
            records.append(
                self._failure_record(job_index, job, state)
                if selected is None
                else self._completed_record(job, state, selected)
            )
        return records

    @staticmethod
    def _client() -> _OpenAIClient:
        from openai import OpenAI

        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY must be set")
        return OpenAI(
            api_key=key,
            timeout=HOSTED_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )

    def _restore_costs(self, state: BatchState) -> None:
        self._spent_usd = state.observed_api_usd
        self._spent_by_model = dict(state.observed_by_model_usd)
        self._unverified_failure_risk_usd = (
            state.unverified_failed_request_risk_usd
        )

    def _load_state(self, path: Path) -> BatchState:
        state = BatchState.load(
            path,
            run_provenance_sha256=self.run_provenance_sha256,
            model=self.config.models[0],
        )
        self._restore_costs(state)
        return state

    @staticmethod
    def _terminal(status: str) -> bool:
        return status in {"completed", "failed", "expired", "cancelled"}

    def _retrieve_batch(
        self,
        client: _OpenAIClient,
        state: BatchState,
        state_path: Path,
    ) -> _RemoteBatch | None:
        if state.submission is None:
            raise ValueError("Batch state has no current submission")
        batch = client.batches.retrieve(state.submission.batch_id)
        state.submission = replace(state.submission, status=batch.status)
        if self._terminal(batch.status):
            return batch
        state.publish(state_path)
        print(
            f"OpenAI Batch {batch.id} is {batch.status}; "
            "retry --resume later."
        )
        return None

    @staticmethod
    def _terminal_batch_errors(
        batch: _RemoteBatch,
        state: BatchState,
        errors: dict[str, JsonObject],
    ) -> dict[str, JsonObject]:
        if batch.status == "completed" or errors:
            return errors
        if state.submission is None:
            raise ValueError("Batch state has no current submission")
        return {
            custom_id: {
                "status_code": None,
                "error": {"type": "batch_" + batch.status},
            }
            for custom_id in state.submission.custom_ids
        }

    def _record_outputs(
        self,
        state: BatchState,
        outputs: dict[str, JsonObject],
        errors: dict[str, JsonObject],
    ) -> None:
        for custom_id, body in outputs.items():
            try:
                state.phase_results[custom_id] = self.parse_response(
                    custom_id,
                    body,
                )
            except Exception as exc:
                retryable, opens_circuit = _retry_disposition(exc)
                errors[custom_id] = {
                    "status_code": None,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                    "retryable": retryable,
                    "opens_provider_circuit": opens_circuit,
                    "cost_accounted": bool(
                        getattr(exc, "batch_cost_accounted", False)
                    ),
                }
        state.observed_api_usd = self._spent_usd
        state.observed_by_model_usd = dict(self._spent_by_model)

    @staticmethod
    def _error_disposition(error: JsonObject) -> tuple[bool, bool]:
        retryable = error.get("retryable")
        opens_circuit = error.get("opens_provider_circuit")
        if isinstance(retryable, bool) and isinstance(opens_circuit, bool):
            return retryable, opens_circuit
        status = error.get("status_code")
        value = _BatchRequestError(
            json.dumps(error, default=str),
            status if isinstance(status, int) else None,
        )
        return _retry_disposition(value)

    def _classify_errors(
        self,
        state: BatchState,
        errors: dict[str, JsonObject],
    ) -> set[str]:
        retry_ids: set[str] = set()
        for custom_id, error in errors.items():
            retryable, _opens_circuit = self._error_disposition(error)
            if retryable and state.attempt <= self.config.max_retries:
                retry_ids.add(custom_id)
            else:
                state.phase_failures[custom_id] = error
        return retry_ids

    def _entries_for_retry(
        self,
        state: BatchState,
        retry_ids: set[str],
    ) -> list[tuple[str, StructuredRequest]]:
        if state.phase == "initial":
            return self._initial_entries(self.jobs, retry_ids)
        return self.synthesis_entries(
            self.jobs,
            state.initial_results,
            retry_ids,
        )

    def _retry_reservations(
        self,
        entries: list[tuple[str, StructuredRequest]],
    ) -> dict[str, float]:
        model = self.config.models[0]
        reservations: dict[str, float] = {}
        for custom_id, request in entries:
            input_tokens = self.count_tokens(model, request)
            reservations[custom_id] = (
                request_cost(
                    model,
                    input_tokens,
                    self.config.max_output_tokens,
                    cache_write_input_tokens=cache_write_reservation_tokens(
                        model,
                        request,
                        input_tokens,
                    ),
                )
                or 0.0
            ) * 0.5
        return reservations

    def _apply_retry_budget(
        self,
        state: BatchState,
        errors: dict[str, JsonObject],
        retry_ids: set[str],
        reservations: dict[str, float],
    ) -> bool:
        risk = state.unverified_failed_request_risk_usd + sum(
            reservation
            for custom_id, reservation in reservations.items()
            if errors[custom_id].get("cost_accounted") is not True
        )
        state.unverified_failed_request_risk_usd = risk
        self._unverified_failure_risk_usd = risk
        exceeds_budget = (
            self.config.max_cost_usd is not None
            and self._spent_usd + risk + sum(reservations.values())
            > self.config.max_cost_usd
        )
        if not exceeds_budget:
            return True
        for custom_id in retry_ids:
            state.phase_failures[custom_id] = {
                **errors[custom_id],
                "retry_suppressed": "run cost budget",
            }
        return False

    def _submit_retry(
        self,
        client: _OpenAIClient,
        state: BatchState,
        errors: dict[str, JsonObject],
        retry_ids: set[str],
    ) -> bool:
        if not retry_ids:
            return False
        entries = self._entries_for_retry(state, retry_ids)
        reservations = self._retry_reservations(entries)
        if not self._apply_retry_budget(
            state,
            errors,
            retry_ids,
            reservations,
        ):
            return False
        state.attempt += 1
        self._submit_batch(client, state, entries)
        return True

    def _submit_synthesis(
        self,
        client: _OpenAIClient,
        state: BatchState,
    ) -> bool:
        if state.phase != "initial":
            return False
        entries = self.synthesis_entries(self.jobs, state.initial_results)
        if not entries:
            return False
        state.phase = "synthesis"
        state.attempt = 1
        self._submit_batch(client, state, entries)
        return True

    def _resume_terminal_batch(
        self,
        client: _OpenAIClient,
        state: BatchState,
        state_path: Path,
        batch: _RemoteBatch,
    ) -> BatchOutcome:
        outputs, errors = self._collect_batch_files(client, batch)
        errors = self._terminal_batch_errors(batch, state, errors)
        self._record_outputs(state, outputs, errors)
        retry_ids = self._classify_errors(state, errors)
        if self._submit_retry(client, state, errors, retry_ids):
            return self._outcome()
        if self._submit_synthesis(client, state):
            return self._outcome()
        state.phase = "complete"
        if state.submission is not None:
            state.submission = replace(state.submission, status="completed")
        state.publish(state_path)
        return self._outcome(self.records_from_state(self.jobs, state))

    def run(self) -> BatchOutcome:
        client = self._client()
        state_path = self.config.output_dir / "batch-state.json"
        if not state_path.is_file():
            if self.config.resume:
                raise ValueError("resumed Batch run has no batch-state.json")
            state = BatchState.new(self.run_provenance_sha256)
            self._submit_batch(client, state, self._initial_entries(self.jobs))
            return self._outcome()
        if not self.config.resume:
            raise FileExistsError("Batch state exists; rerun with --resume")
        state = self._load_state(state_path)
        if state.phase == "complete" and (
            self.config.output_dir / "summary.json"
        ).is_file():
            return self._outcome()
        batch = self._retrieve_batch(client, state, state_path)
        if batch is None:
            return self._outcome()
        return self._resume_terminal_batch(client, state, state_path, batch)
