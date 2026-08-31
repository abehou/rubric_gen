"""Plan and execute rubric-free structured score requests."""

from __future__ import annotations

import os
from typing import Callable

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    generate_structured,
)
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.judge import JUDGE_MAX_ATTEMPTS
from rubric_gen.submission_revision.evaluation import (
    absolute_score,
    pairwise_preference,
)
from rubric_gen.submission_revision.evaluation.jobs import (
    ARTIFACTS,
    ORDERINGS,
    RubricFreeAbsoluteScoreJob,
    EvaluationConfig,
    EvaluationTarget,
    PairwisePreferenceJob,
    PreparedRubricFreeScores,
    _rubric_free_absolute_score_request,
    _absolute_judgment_identity,
    _accept_predispatch_plan,
    _assert_accepted_job_plan,
    _rubric_free_score_implementation_identity,
    _rubric_free_score_plan_entry,
    _pairwise_judgment_identity,
    _pairwise_preference_request,
    _stage_caps,
)
from rubric_gen.submission_revision.evaluation.store import EvaluationStore
from rubric_gen.submission_revision.rubrics.schema import load_json_strict

class RubricFreeScoreStage:
    def __init__(
        self,
        config: EvaluationConfig,
        targets: tuple[EvaluationTarget, ...],
        *,
        generation_operation: Callable[[str, StructuredRequest], GenerationResult]
        | None = None,
    ) -> None:
        self.config = config
        self.targets = targets
        self.absolute_output = EvaluationStore(config.output_dir / "absolute_score")
        self.pairwise_output = EvaluationStore(
            config.output_dir / "pairwise_preference"
        )
        self.root = config.output_dir.resolve()
        self.generation_operation = generation_operation
        self._prepared: PreparedRubricFreeScores | None = None

    def preflight(self) -> None:
        """Prepare and cap all requests without output or provider calls."""

        if self._prepared is not None:
            return
        targets = self.targets
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        implementation_identity = _rubric_free_score_implementation_identity()
        absolute_jobs = tuple(
            RubricFreeAbsoluteScoreJob(
                target=target,
                model=model,
                artifact=artifact,
                implementation_identity=implementation_identity,
            )
            for target in targets
            for model in models
            for artifact in ARTIFACTS
        )
        pairwise_jobs = tuple(
            PairwisePreferenceJob(
                target=target,
                model=model,
                ordering=ordering,
                implementation_identity=implementation_identity,
            )
            for target in targets
            if len(target.submission_ids) >= 2
            for model in models
            for ordering in ORDERINGS
        )
        unique_absolute_jobs = tuple({
            job.key: job for job in reversed(absolute_jobs)
        }.values())
        unique_pairwise_jobs = tuple({
            job.key: job for job in reversed(pairwise_jobs)
        }.values())
        self._prepared = PreparedRubricFreeScores(
            targets=targets,
            models=models,
            implementation_identity=implementation_identity,
            absolute_jobs=absolute_jobs,
            pairwise_jobs=pairwise_jobs,
            unique_absolute_jobs=unique_absolute_jobs,
            unique_pairwise_jobs=unique_pairwise_jobs,
            predispatch_plan=self._predispatch_plan(
                unique_absolute_jobs,
                unique_pairwise_jobs,
            ),
        )


    def _predispatch_plan(
        self,
        absolute_jobs: tuple[RubricFreeAbsoluteScoreJob, ...],
        pairwise_jobs: tuple[PairwisePreferenceJob, ...],
    ) -> dict[str, object]:
        benchmarks = {
            job.target.benchmark for job in (*absolute_jobs, *pairwise_jobs)
        }
        if len(benchmarks) != 1:
            raise RuntimeError("revision rubric-free evaluation jobs must use one benchmark")
        planned: list[
            tuple[str, str, str, StructuredRequest]
        ] = []
        planned.extend(
            (
                job.key,
                "absolute",
                job.model,
                _rubric_free_absolute_score_request(job),
            )
            for job in absolute_jobs
        )
        planned.extend(
            (
                job.key,
                "pairwise",
                job.model,
                _pairwise_preference_request(job),
            )
            for job in pairwise_jobs
        )
        jobs: list[dict[str, object]] = []
        request_bytes = 0
        output_tokens = 0
        largest_request_bytes = 0
        with TerminalProgress(
            total=len(planned),
            description="revision rubric-free evaluation planning",
            unit="judgment",
        ) as progress:
            for key, instrument, model, request in planned:
                progress.set_status(key[:12])
                entry = _rubric_free_score_plan_entry(
                    key=key,
                    instrument=instrument,
                    model=model,
                    request=request,
                )
                content_bytes = int(entry["request_bytes"])
                request_bytes += content_bytes
                output_tokens += int(entry["max_output_tokens"])
                largest_request_bytes = max(
                    largest_request_bytes,
                    content_bytes,
                )
                jobs.append(entry)
                progress.update()
        base = {
            "benchmark": next(iter(benchmarks)).value,
            "grading_engine": "structured-generation",
            "dispatch_count": len(planned),
            "calls": len(planned),
            "request_byte_measurement": (
                "instructions-plus-evidence-plus-schema-name-plus-canonical-schema"
            ),
            "largest_request_bytes_per_call": largest_request_bytes,
            "request_bytes": request_bytes,
            "output_tokens": output_tokens,
        }
        return _accept_predispatch_plan(
            stage="rubric_free_evaluation",
            base=base,
            jobs=jobs,
            outer_attempt_limit=JUDGE_MAX_ATTEMPTS,
            caps=_stage_caps(
                self.config.experiment.outcome_audit,
                "rubric_free_evaluation",
            ),
        )

    def _run_absolute_job(
        self,
        job: RubricFreeAbsoluteScoreJob,
    ) -> dict[str, object]:
        request = _rubric_free_absolute_score_request(job)
        return self._run_structured_judgment(
            model=job.model,
            request=request,
            key=job.key,
            instrument="absolute",
            identity=_absolute_judgment_identity(job, request),
            validator=absolute_score.validate_verdict,
        )

    def _run_pairwise_job(
        self,
        job: PairwisePreferenceJob,
    ) -> dict[str, object]:
        request = _pairwise_preference_request(job)
        return self._run_structured_judgment(
            model=job.model,
            request=request,
            key=job.key,
            instrument="pairwise",
            identity=_pairwise_judgment_identity(job, request),
            validator=pairwise_preference.validate_verdict,
        )

    def _run_structured_judgment(
        self,
        *,
        model: str,
        request: StructuredRequest,
        key: str,
        instrument: str,
        identity: dict[str, object],
        validator: Callable[[object], None],
    ) -> dict[str, object]:
        output = self._output_for(instrument)
        record_name = f"{key}.json"
        output.ensure_directory("records")
        record_path = output.regular_file(
            "records",
            record_name,
            allow_missing=True,
        )
        max_attempts = JUDGE_MAX_ATTEMPTS
        if os.path.lexists(record_path):
            record = read_json_object(record_path, "revision rubric-free evaluation record")
            _validate_record(
                record=record,
                identity=identity,
                validator=validator,
                model=model,
                max_attempts=max_attempts,
            )
            return record
        value: dict[str, object] | None = None
        generation: GenerationResult | None = None
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                self._assert_current_dispatch(
                    key=key,
                    instrument=instrument,
                    model=model,
                    request=request,
                )
                generation = self._generate(model, request)
                parsed = load_json_strict(generation.text)
                validator(parsed)
                assert isinstance(parsed, dict)
                value = parsed
                break
            except (RuntimeError, ValueError) as exc:
                last_error = exc
        if generation is None or value is None:
            raise RuntimeError(
                f"rubric-free score judge failed after {max_attempts} attempts: "
                f"{last_error}"
            ) from last_error
        record = {
            **identity,
            "verdict": value,
            "raw_response": generation.text,
            "raw_response_sha256": sha256_text(generation.text),
            "generation": generation.provenance(),
            "attempt_count": attempt,
        }
        _validate_record(
            record=record,
            identity=identity,
            validator=validator,
            model=model,
            max_attempts=max_attempts,
        )
        output.write_json(("records", record_name), record)
        return record

    def _output_for(self, instrument: str) -> EvaluationStore:
        if instrument == "absolute":
            return self.absolute_output
        if instrument == "pairwise":
            return self.pairwise_output
        raise ValueError(f"unknown rubric-free score instrument: {instrument}")

    def _assert_current_dispatch(
        self,
        *,
        key: str,
        instrument: str,
        model: str,
        request: StructuredRequest,
    ) -> None:
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("revision rubric-free evaluation dispatch has no accepted stage plan")
        current = _rubric_free_score_plan_entry(
            key=key,
            instrument=instrument,
            model=model,
            request=request,
        )
        _assert_accepted_job_plan(
            stage="rubric_free_evaluation",
            plan=prepared.predispatch_plan,
            current=current,
        )

    def _generate(
        self,
        model: str,
        request: StructuredRequest,
    ) -> GenerationResult:
        if self.generation_operation is not None:
            return self.generation_operation(model, request)
        return generate_structured(model, request)


def _validate_record(
    *,
    record: dict[str, object],
    identity: dict[str, object],
    validator: Callable[[object], None],
    model: str,
    max_attempts: int,
) -> None:
    result_keys = {
        "verdict",
        "raw_response",
        "raw_response_sha256",
        "generation",
        "attempt_count",
    }
    if set(record) != set(identity) | result_keys:
        raise RuntimeError("rubric-free score record fields changed")
    if any(record[key] != value for key, value in identity.items()):
        raise RuntimeError("rubric-free score record identity changed")
    try:
        validator(record["verdict"])
    except ValueError as exc:
        raise RuntimeError("rubric-free score record verdict changed") from exc
    raw_response = record["raw_response"]
    if (
        type(raw_response) is not str
        or not raw_response.strip()
        or record["raw_response_sha256"] != sha256_text(raw_response)
    ):
        raise RuntimeError("rubric-free score record raw response hash changed")
    try:
        decoded_response = load_json_strict(raw_response)
        validator(decoded_response)
    except ValueError as exc:
        raise RuntimeError("rubric-free score record raw response changed") from exc
    if decoded_response != record["verdict"]:
        raise RuntimeError("rubric-free score record disagrees with raw response")
    attempt_count = record["attempt_count"]
    if (
        type(attempt_count) is not int
        or not 1 <= attempt_count <= max_attempts
    ):
        raise RuntimeError("rubric-free score record attempt count changed")
    generation = record["generation"]
    generation_keys = {
        "provider",
        "requested_model",
        "effective_model",
        "response_id",
        "request_parameters",
        "provider_metadata",
    }
    if type(generation) is not dict or set(generation) != generation_keys:
        raise RuntimeError("rubric-free score record generation fields changed")
    for name in (
        "provider",
        "requested_model",
        "effective_model",
        "response_id",
    ):
        value = generation[name]
        if type(value) is not str or not value.strip():
            raise RuntimeError(
                f"rubric-free score record generation value changed: {name}"
            )
    if generation["requested_model"] != model:
        raise RuntimeError("rubric-free score record requested model changed")
    if (
        type(generation["request_parameters"]) is not dict
        or type(generation["provider_metadata"]) is not dict
    ):
        raise RuntimeError("rubric-free score record generation metadata changed")
