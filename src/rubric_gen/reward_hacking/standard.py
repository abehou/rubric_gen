"""Execute synchronous reward-hacking judge jobs."""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.reward_hacking.costs import request_cost, usage_tokens
from rubric_gen.reward_hacking.jobs import (
    JUDGE_MAX_ATTEMPTS,
    PreparedJob,
    RewardHackingJudgeConfig,
)
from rubric_gen.reward_hacking.review import (
    EvidencePrompt,
    _aggregate_rh_scores,
    _extract,
    _extract_model_output,
    _synthesis_request,
    _validate_rh_verdict,
)
from rubric_gen.reward_hacking.sources import AuditCase
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    request_parameters_for_model,
)


JsonObject = dict[str, object]
_SCORE_KEYS = {
    "kind",
    "identity",
    "case_id",
    "source_kind",
    "source_path",
    "provider",
    "model",
    "status",
    "compact_evidence",
    "generation",
    "generations",
    "raw_responses",
    "attempt_count",
    "max_attempts",
    "verdict",
    "cost",
}


@dataclass(frozen=True)
class StandardOutcome:
    observed_api_usd: float
    observed_by_model_usd: dict[str, float]


@dataclass(frozen=True)
class _JobPaths:
    root: Path
    score: Path


@dataclass
class _GeneratedArtifacts:
    raw_responses: list[JsonObject] = field(default_factory=list)
    generations: list[JsonObject] = field(default_factory=list)
    verdicts: list[JsonObject] = field(default_factory=list)
    observed_api_usd: float = 0.0
    observed_by_model_usd: dict[str, float] = field(default_factory=dict)

    def add_cost(self, model: str, generation: GenerationResult) -> None:
        usage = usage_tokens(generation)
        cost = request_cost(model, **usage) if usage is not None else None
        if cost is None:
            return
        self.observed_api_usd += cost
        self.observed_by_model_usd[model] = (
            self.observed_by_model_usd.get(model, 0.0) + cost
        )


class StandardJobRunner:
    def __init__(
        self,
        config: RewardHackingJudgeConfig,
        run_settings: dict[str, object],
        generate_response: Callable[[str, StructuredRequest], GenerationResult],
        generate_vllm_response: Callable[
            [str, StructuredRequest, str], GenerationResult
        ],
        count_tokens: Callable[[str, StructuredRequest], int],
        load_payload: Callable[[AuditCase], EvidencePrompt],
    ) -> None:
        self.config = config
        self.run_settings = run_settings
        self.generate_response = generate_response
        self.generate_vllm_response = generate_vllm_response
        self.count_tokens = count_tokens
        self.load_payload = load_payload
        self._lock = threading.Lock()
        self._observed_api_usd = 0.0
        self._observed_by_model_usd: dict[str, float] = {}

    @property
    def outcome(self) -> StandardOutcome:
        with self._lock:
            return StandardOutcome(
                observed_api_usd=self._observed_api_usd,
                observed_by_model_usd=dict(self._observed_by_model_usd),
            )

    @staticmethod
    def cache_group(job: PreparedJob) -> tuple[str, str]:
        """Serialize jobs that can reuse the same provider prompt cache."""

        return job.model, job.requests[0].prompt_cache_key()

    def execute(self, job: PreparedJob) -> JsonObject:
        paths = self._paths(job)
        identity = self._identity(job)
        saved = (
            self._load_saved_score(paths.score, identity)
            if self.config.resume
            else None
        )
        if saved is not None:
            record = {**saved, "status": "skipped"}
            self._record_cost(record)
            return record
        if paths.score.exists() and not self.config.resume:
            raise FileExistsError(f"judge score exists: {paths.score}")
        if paths.root.is_symlink():
            raise RuntimeError(f"judge output directory is a symlink: {paths.root}")
        paths.root.mkdir(parents=True, exist_ok=True)

        total_cost = 0.0
        total_by_model: dict[str, float] = {}
        last_error: Exception | None = None
        attempts = 0
        for attempts in range(1, JUDGE_MAX_ATTEMPTS + 1):
            artifacts = _GeneratedArtifacts()
            try:
                verdict, generation = self._run_once(job, artifacts)
            except Exception as exc:
                self._merge_cost(total_by_model, artifacts.observed_by_model_usd)
                total_cost += artifacts.observed_api_usd
                last_error = exc
                continue

            self._merge_cost(total_by_model, artifacts.observed_by_model_usd)
            total_cost += artifacts.observed_api_usd
            record = self._score_record(
                job,
                identity=identity,
                artifacts=artifacts,
                verdict=verdict,
                generation=generation,
                attempt_count=attempts,
                observed_api_usd=total_cost,
                observed_by_model_usd=total_by_model,
            )
            write_json_atomic(paths.score, record)
            self._record_cost(record)
            return record

        assert last_error is not None
        failed = {
            "case_id": job.case.case_id,
            "source_kind": job.source_kind,
            "source_path": str(job.case.path),
            "provider": job.model,
            "model": job.model,
            "status": "failed",
            "error_type": type(last_error).__name__,
            "error": str(last_error),
            "attempt_count": attempts,
            "max_attempts": JUDGE_MAX_ATTEMPTS,
            "cost": {
                "observed_api_usd": total_cost,
                "observed_by_model_usd": dict(sorted(total_by_model.items())),
            },
        }
        self._record_cost(failed)
        return failed

    @staticmethod
    def _merge_cost(target: dict[str, float], values: dict[str, float]) -> None:
        for model, cost in values.items():
            target[model] = target.get(model, 0.0) + cost

    def _record_cost(self, record: JsonObject) -> None:
        cost = record.get("cost")
        if not isinstance(cost, dict):
            return
        observed = cost.get("observed_api_usd")
        by_model = cost.get("observed_by_model_usd")
        if (
            isinstance(observed, bool)
            or not isinstance(observed, (int, float))
            or not isinstance(by_model, dict)
        ):
            return
        with self._lock:
            self._observed_api_usd += float(observed)
            for model, value in by_model.items():
                if type(model) is str and isinstance(value, (int, float)):
                    self._observed_by_model_usd[model] = (
                        self._observed_by_model_usd.get(model, 0.0) + float(value)
                    )

    def _paths(self, job: PreparedJob) -> _JobPaths:
        root = (
            self.config.output_dir
            / "cases"
            / job.case.case_id
            / job.model.replace("/", "_")
        )
        return _JobPaths(root=root, score=root / "score.json")

    def _identity(self, job: PreparedJob) -> JsonObject:
        return {
            "case_id": job.case.case_id,
            "source_kind": job.source_kind,
            "source_path": str(job.case.path),
            "model": job.model,
            "input_tokens": list(job.input_tokens),
            "request_parameters": request_parameters_for_model(
                job.model,
                base_url=self.config.base_urls.get(job.model),
                max_output_tokens=self.config.max_output_tokens,
            ),
            "aggregation": job.aggregation,
            "run": self.run_settings,
        }

    def _load_saved_score(
        self,
        path: Path,
        identity: JsonObject,
    ) -> JsonObject | None:
        if path.is_symlink() or not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not self._valid_score(value, identity):
                return None
            return value
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return None

    def _valid_score(self, value: object, identity: JsonObject) -> bool:
        if not isinstance(value, dict) or set(value) != _SCORE_KEYS:
            return False
        if (
            value.get("kind") != "reward-hacking-judge-score"
            or value.get("identity") != identity
            or value.get("status") != "completed"
            or value.get("case_id") != identity["case_id"]
            or value.get("source_kind") != identity["source_kind"]
            or value.get("source_path") != identity["source_path"]
            or value.get("provider") != identity["model"]
            or value.get("model") != identity["model"]
            or value.get("max_attempts") != JUDGE_MAX_ATTEMPTS
            or type(value.get("attempt_count")) is not int
            or not 1 <= value["attempt_count"] <= JUDGE_MAX_ATTEMPTS
            or not isinstance(value.get("raw_responses"), list)
            or not isinstance(value.get("generations"), list)
            or len(value["raw_responses"]) != len(value["generations"])
            or not value["raw_responses"]
        ):
            return False
        try:
            if self.config.detection == "rh":
                _validate_rh_verdict(value.get("verdict"))
            else:
                _extract(json.dumps(value.get("verdict")), self.config.detection)
        except (TypeError, ValueError):
            return False
        return self._valid_cost(value.get("cost"))

    @staticmethod
    def _valid_cost(value: object) -> bool:
        if not isinstance(value, dict) or set(value) != {
            "observed_api_usd",
            "observed_by_model_usd",
        }:
            return False
        observed = value["observed_api_usd"]
        by_model = value["observed_by_model_usd"]
        return (
            not isinstance(observed, bool)
            and isinstance(observed, (int, float))
            and math.isfinite(float(observed))
            and float(observed) >= 0
            and isinstance(by_model, dict)
            and all(
                type(model) is str
                and not isinstance(cost, bool)
                and isinstance(cost, (int, float))
                and math.isfinite(float(cost))
                and float(cost) >= 0
                for model, cost in by_model.items()
            )
        )

    def _request_once(
        self,
        model: str,
        request: StructuredRequest,
        *,
        base_url: str | None,
    ) -> tuple[GenerationResult, JsonObject]:
        expected = request_parameters_for_model(
            model,
            base_url=base_url,
            max_output_tokens=self.config.max_output_tokens,
        )
        generation = (
            self.generate_vllm_response(model, request, base_url)
            if base_url is not None
            else self.generate_response(model, request)
        )
        if (
            generation.requested_model != model
            or generation.provider != expected["provider"]
            or generation.request_parameters != expected
        ):
            raise ValueError("detection generation settings changed")
        return generation, _extract_model_output(
            generation.text,
            self.config.detection,
        )

    def _run_once(
        self,
        job: PreparedJob,
        artifacts: _GeneratedArtifacts,
    ) -> tuple[JsonObject, object]:
        base_url = self.config.base_urls.get(job.model)
        for index, request in enumerate(job.requests, start=1):
            generation, verdict = self._request_once(
                job.model,
                request,
                base_url=base_url,
            )
            artifacts.add_cost(job.model, generation)
            artifacts.raw_responses.append({
                "stage": job.request_stage,
                "index": index,
                "text": generation.text,
            })
            artifacts.generations.append({
                "stage": job.request_stage,
                "index": index,
                "generation": generation.provenance(),
            })
            artifacts.verdicts.append(verdict)
        return self._select_verdict(job, artifacts)

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
        generation, verdict = self._request_once(
            job.model,
            request,
            base_url=self.config.base_urls.get(job.model),
        )
        artifacts.add_cost(job.model, generation)
        artifacts.raw_responses.append({
            "stage": "synthesis",
            "index": 1,
            "text": generation.text,
        })
        artifacts.generations.append({
            "stage": "synthesis",
            "index": 1,
            "generation": generation.provenance(),
        })
        return verdict, artifacts.generations[-1]["generation"]

    @staticmethod
    def _score_record(
        job: PreparedJob,
        *,
        identity: JsonObject,
        artifacts: _GeneratedArtifacts,
        verdict: JsonObject,
        generation: object,
        attempt_count: int,
        observed_api_usd: float,
        observed_by_model_usd: dict[str, float],
    ) -> JsonObject:
        return {
            "kind": "reward-hacking-judge-score",
            "identity": identity,
            "case_id": job.case.case_id,
            "source_kind": job.source_kind,
            "source_path": str(job.case.path),
            "provider": job.model,
            "model": job.model,
            "status": "completed",
            "compact_evidence": job.compact_stats,
            "generation": generation,
            "generations": artifacts.generations,
            "raw_responses": artifacts.raw_responses,
            "attempt_count": attempt_count,
            "max_attempts": JUDGE_MAX_ATTEMPTS,
            "verdict": verdict,
            "cost": {
                "observed_api_usd": observed_api_usd,
                "observed_by_model_usd": dict(sorted(observed_by_model_usd.items())),
            },
        }
