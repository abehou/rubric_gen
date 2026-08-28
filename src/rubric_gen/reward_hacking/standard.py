"""Execute standard reward-hacking panel requests."""

from __future__ import annotations

import json
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.evidence.index import index_implementation_sha256
from rubric_gen.reward_hacking.costs import (
    cache_write_reservation_tokens,
    request_cost,
    usage_tokens,
)
from rubric_gen.reward_hacking.jobs import PreparedJob, RewardHackingJudgeConfig
from rubric_gen.reward_hacking.review import (
    EvidencePrompt,
    _aggregate_rh_scores,
    _extract,
    _extract_model_output,
    _retry_disposition,
    _synthesis_request,
    _validate_rh_verdict,
)
from rubric_gen.reward_hacking.sources import AuditCase
from rubric_gen.reward_hacking.standard_state import StandardCostState
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    request_parameters_for_model,
)


JsonObject = dict[str, object]


@dataclass(frozen=True)
class StandardOutcome:
    observed_api_usd: float
    observed_by_model_usd: dict[str, float]
    unverified_failed_request_risk_usd: float


@dataclass(frozen=True)
class _JobPaths:
    root: Path
    verdict: Path
    metadata: Path
    prompts: Path
    responses: Path
    generations: Path

    @property
    def artifacts(self) -> dict[str, Path]:
        return {
            "prompts_sha256": self.prompts,
            "responses_sha256": self.responses,
            "generations_sha256": self.generations,
            "verdict_sha256": self.verdict,
        }


@dataclass
class _GeneratedArtifacts:
    prompts: list[JsonObject]
    responses: list[JsonObject]
    generations: list[JsonObject]
    verdicts: list[JsonObject]
    attempt_count: int

    @classmethod
    def empty(cls) -> _GeneratedArtifacts:
        return cls([], [], [], [], 0)


class StandardJobRunner:
    def __init__(
        self,
        config: RewardHackingJudgeConfig,
        run_provenance_sha256: str,
        implementation_sha256s: dict[str, str],
        generate_response: Callable[
            [str, StructuredRequest], GenerationResult
        ],
        generate_vllm_response: Callable[
            [str, StructuredRequest, str], GenerationResult
        ],
        count_tokens: Callable[[str, StructuredRequest], int],
        load_payload: Callable[[AuditCase], EvidencePrompt],
    ) -> None:
        self.config = config
        self.run_provenance_sha256 = run_provenance_sha256
        self.implementation_sha256s = implementation_sha256s
        self.generate_response = generate_response
        self.generate_vllm_response = generate_vllm_response
        self.count_tokens = count_tokens
        self.load_payload = load_payload
        self._lock = threading.Lock()
        self._circuit_open: dict[str, str] = {}
        self._cost_state = StandardCostState.new(
            run_provenance_sha256,
            config.max_cost_usd,
        )

    @property
    def _cost_path(self) -> Path:
        return self.config.output_dir / "cost-state.json"

    @property
    def outcome(self) -> StandardOutcome:
        return StandardOutcome(
            observed_api_usd=self._cost_state.observed_api_usd,
            observed_by_model_usd=dict(
                self._cost_state.observed_by_model_usd
            ),
            unverified_failed_request_risk_usd=(
                self._cost_state.unverified_failed_request_risk_usd
            ),
        )

    def initialize_cost_state(self) -> None:
        path = self._cost_path
        if path.is_symlink():
            raise ValueError("cost state path is not a regular file")
        if not path.is_file():
            if self.config.resume:
                raise ValueError("resumed run has no strict cost-state.json")
            self._cost_state.publish(path)
            return
        if not self.config.resume:
            raise FileExistsError("cost state exists; rerun with --resume")
        self._cost_state = StandardCostState.load(
            path,
            run_provenance_sha256=self.run_provenance_sha256,
            models=self.config.models,
            budget_usd=self.config.max_cost_usd,
        )
        self._cost_state.publish(path)

    def _generate_budgeted(
        self,
        model: str,
        request: StructuredRequest,
        *,
        input_tokens: int,
        base_url: str | None,
    ) -> GenerationResult:
        cache_write_tokens = cache_write_reservation_tokens(
            model,
            request,
            input_tokens,
        )
        reservation = request_cost(
            model,
            input_tokens,
            self.config.max_output_tokens,
            cache_write_input_tokens=cache_write_tokens,
        ) or 0.0
        with self._lock:
            if model in self._circuit_open:
                raise RuntimeError(
                    f"provider circuit is open for {model}: "
                    f"{self._circuit_open[model]}"
                )
            self._cost_state.reserve(model, reservation)
            self._cost_state.publish(self._cost_path)
        try:
            generation = (
                self.generate_vllm_response(model, request, base_url)
                if base_url is not None
                else self.generate_response(model, request)
            )
        except Exception:
            with self._lock:
                self._cost_state.record_failure(reservation)
                self._cost_state.publish(self._cost_path)
            raise
        usage = usage_tokens(generation)
        actual = request_cost(model, **usage) if usage is not None else reservation
        with self._lock:
            self._cost_state.record_success(model, reservation, actual)
            self._cost_state.publish(self._cost_path)
        return generation

    def _request_with_retries(
        self,
        model: str,
        request: StructuredRequest,
        *,
        input_tokens: int,
        base_url: str | None,
    ) -> tuple[GenerationResult, JsonObject, int]:
        expected = request_parameters_for_model(
            model,
            base_url=base_url,
            max_output_tokens=self.config.max_output_tokens,
        )
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
                    or generation.provider != expected["provider"]
                    or generation.request_parameters != expected
                ):
                    raise ValueError("detection generation provenance mismatch")
                verdict = _extract_model_output(
                    generation.text,
                    self.config.detection,
                )
                return generation, verdict, attempt
            except Exception as exc:
                retryable, opens_circuit = _retry_disposition(exc)
                if opens_circuit:
                    with self._lock:
                        self._circuit_open[model] = str(exc)
                if not retryable or attempt > self.config.max_retries:
                    setattr(exc, "attempt_count", attempt)
                    setattr(exc, "retryable", retryable)
                    raise
        raise AssertionError("request retry loop did not terminate")

    @staticmethod
    def cache_group(job: PreparedJob) -> tuple[str, str]:
        return job.model, job.requests[0].prompt_cache_key()

    def execute(self, job: PreparedJob) -> JsonObject:
        try:
            return self._execute(job)
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

    def _paths(self, job: PreparedJob) -> _JobPaths:
        root = (
            self.config.output_dir
            / "cases"
            / job.case.case_id
            / job.model.replace("/", "_")
        )
        return _JobPaths(
            root=root,
            verdict=root / "verdict.json",
            metadata=root / "metadata.json",
            prompts=root / "prompts.json",
            responses=root / "responses.json",
            generations=root / "generations.json",
        )

    def _resume_identity(self, job: PreparedJob) -> JsonObject:
        base_url = self.config.base_urls.get(job.model)
        return {
            "implementation_sha256s": self.implementation_sha256s,
            "evidence_index_sha256": index_implementation_sha256(),
            "run_provenance_sha256": self.run_provenance_sha256,
            "detection": self.config.detection,
            "requested_model": job.model,
            "request_sha256s": [
                sha256_text(request.flat_prompt()) for request in job.requests
            ],
            "input_tokens": list(job.input_tokens),
            "request_parameters": request_parameters_for_model(
                job.model,
                base_url=base_url,
                max_output_tokens=self.config.max_output_tokens,
            ),
        }

    @staticmethod
    def _load_metadata(path: Path) -> JsonObject | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _artifacts_current(paths: _JobPaths, metadata: JsonObject) -> bool:
        artifacts = metadata.get("artifacts")
        return isinstance(artifacts, dict) and all(
            type(artifacts.get(name)) is str
            and path.is_file()
            and sha256_file(path) == artifacts[name]
            for name, path in paths.artifacts.items()
        )

    @staticmethod
    def _generations_current(paths: _JobPaths, metadata: JsonObject) -> bool:
        if not paths.generations.is_file():
            return False
        try:
            return (
                json.loads(paths.generations.read_text(encoding="utf-8"))
                == metadata.get("generations")
            )
        except json.JSONDecodeError:
            return False

    def _metadata_current(
        self,
        job: PreparedJob,
        paths: _JobPaths,
        metadata: JsonObject | None,
        identity: JsonObject,
    ) -> bool:
        return (
            metadata is not None
            and set(metadata) == {
                "resume_identity",
                "compact_evidence",
                "attempt_count",
                "generations",
                "artifacts",
            }
            and metadata.get("resume_identity") == identity
            and metadata.get("compact_evidence") == job.compact_stats
            and isinstance(metadata.get("generations"), list)
            and self._artifacts_current(paths, metadata)
            and self._generations_current(paths, metadata)
        )

    def _resume_record(
        self,
        job: PreparedJob,
        paths: _JobPaths,
        metadata: JsonObject,
    ) -> JsonObject:
        verdict_text = paths.verdict.read_text(encoding="utf-8")
        verdict = (
            _validate_rh_verdict(json.loads(verdict_text))
            if self.config.detection == "rh"
            else _extract(verdict_text, self.config.detection)
        )
        generations = metadata["generations"]
        if not isinstance(generations, list) or not generations:
            raise ValueError("current job metadata has no generations")
        selected = (
            int(verdict["selected_chunk"]) - 1
            if self.config.detection == "rh"
            else len(generations) - 1
        )
        generation = generations[selected]
        if not isinstance(generation, dict):
            raise ValueError("current job generation has invalid structure")
        return self._record(
            job,
            status="skipped",
            verdict=verdict,
            generation=generation["generation"],
            generations=generations,
            attempt_count=int(metadata["attempt_count"]),
        )

    def _reset_root(self, paths: _JobPaths) -> None:
        if os.path.lexists(paths.root):
            if not self.config.resume:
                raise FileExistsError(
                    f"model output exists: {paths.root}; use --resume"
                )
            if paths.root.is_symlink() or not paths.root.is_dir():
                raise RuntimeError(
                    f"invalid reward-hacking model output directory: {paths.root}"
                )
            shutil.rmtree(paths.root)
        paths.root.mkdir(parents=True)

    def _run_primary_requests(self, job: PreparedJob) -> _GeneratedArtifacts:
        artifacts = _GeneratedArtifacts.empty()
        base_url = self.config.base_urls.get(job.model)
        for index, (request, input_tokens) in enumerate(
            zip(job.requests, job.input_tokens, strict=True),
            start=1,
        ):
            generation, verdict, attempts = self._request_with_retries(
                job.model,
                request,
                input_tokens=input_tokens,
                base_url=base_url,
            )
            artifacts.attempt_count += attempts
            artifacts.prompts.append({
                "stage": job.request_stage,
                "index": index,
                "input_tokens": input_tokens,
                "prompt": request.flat_prompt(),
            })
            artifacts.responses.append({
                "stage": job.request_stage,
                "index": index,
                "text": generation.text,
            })
            artifacts.generations.append({
                "stage": job.request_stage,
                "index": index,
                "input_tokens": input_tokens,
                "generation": generation.provenance(),
            })
            artifacts.verdicts.append(verdict)
        return artifacts

    def _run_synthesis(
        self,
        job: PreparedJob,
        artifacts: _GeneratedArtifacts,
    ) -> tuple[JsonObject, object]:
        request = _synthesis_request(
            self.load_payload(job.case),
            self.config.detection,
            artifacts.verdicts,
            max_output_tokens=self.config.max_output_tokens,
        )
        tokens = self.count_tokens(job.model, request)
        if tokens > self.config.max_input_tokens:
            raise ValueError(
                f"chunk synthesis requires {tokens} tokens, above "
                f"the {self.config.max_input_tokens} token ceiling"
            )
        generation, verdict, attempts = self._request_with_retries(
            job.model,
            request,
            input_tokens=tokens,
            base_url=self.config.base_urls.get(job.model),
        )
        artifacts.attempt_count += attempts
        artifacts.prompts.append({
            "stage": "synthesis",
            "index": 1,
            "input_tokens": tokens,
            "prompt": request.flat_prompt(),
        })
        artifacts.responses.append({
            "stage": "synthesis",
            "index": 1,
            "text": generation.text,
        })
        artifacts.generations.append({
            "stage": "synthesis",
            "index": 1,
            "input_tokens": tokens,
            "generation": generation.provenance(),
        })
        return verdict, artifacts.generations[-1]["generation"]

    def _select_verdict(
        self,
        job: PreparedJob,
        artifacts: _GeneratedArtifacts,
    ) -> tuple[JsonObject, object]:
        if job.aggregation == "max_score":
            verdict = _aggregate_rh_scores(artifacts.verdicts)
            selected = int(verdict["selected_chunk"]) - 1
            return verdict, artifacts.generations[selected]["generation"]
        if job.requires_synthesis:
            return self._run_synthesis(job, artifacts)
        return artifacts.verdicts[0], artifacts.generations[0]["generation"]

    @staticmethod
    def _publish(
        job: PreparedJob,
        paths: _JobPaths,
        identity: JsonObject,
        artifacts: _GeneratedArtifacts,
        verdict: JsonObject,
    ) -> None:
        write_json_atomic(paths.prompts, artifacts.prompts)
        write_json_atomic(paths.responses, artifacts.responses)
        write_json_atomic(paths.generations, artifacts.generations)
        write_json_atomic(paths.verdict, verdict)
        write_json_atomic(paths.metadata, {
            "resume_identity": identity,
            "compact_evidence": job.compact_stats,
            "attempt_count": artifacts.attempt_count,
            "generations": artifacts.generations,
            "artifacts": {
                name: sha256_file(path)
                for name, path in paths.artifacts.items()
            },
        })

    def _record(
        self,
        job: PreparedJob,
        *,
        status: str,
        verdict: JsonObject,
        generation: object,
        generations: list[object],
        attempt_count: int,
    ) -> JsonObject:
        return {
            "case_id": job.case.case_id,
            "source_kind": job.source_kind,
            "source_path": str(job.case.path),
            "provider": job.model,
            "model": job.model,
            "status": status,
            "compact_evidence": job.compact_stats,
            "generation": generation,
            "generations": generations,
            "attempt_count": attempt_count,
            "max_retries": self.config.max_retries,
            "retry_exhausted": False,
            "verdict": verdict,
        }

    def _execute(self, job: PreparedJob) -> JsonObject:
        paths = self._paths(job)
        identity = self._resume_identity(job)
        metadata = self._load_metadata(paths.metadata)
        if (
            self.config.resume
            and paths.verdict.is_file()
            and self._metadata_current(job, paths, metadata, identity)
        ):
            if metadata is None:
                raise AssertionError("current metadata was not loaded")
            return self._resume_record(job, paths, metadata)
        self._reset_root(paths)
        artifacts = self._run_primary_requests(job)
        verdict, generation = self._select_verdict(job, artifacts)
        self._publish(job, paths, identity, artifacts, verdict)
        return self._record(
            job,
            status="completed",
            verdict=verdict,
            generation=generation,
            generations=artifacts.generations,
            attempt_count=artifacts.attempt_count,
        )
