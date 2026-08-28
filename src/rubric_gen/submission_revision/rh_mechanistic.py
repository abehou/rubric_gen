"""Mechanistic reward-hacking stage planning and artifact validation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean, median

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.judge import (
    JUDGE_MAX_ATTEMPTS,
    JudgeArtifacts,
    SCORING_IDENTITY_KEYS,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.judging.preflight import (
    JudgeDispatchInput,
    preflight_judge_dispatches,
)
from rubric_gen.submission_revision.rh_audit_judge import RhAuditRubricJudge
from rubric_gen.submission_revision.rh_protocol import (
    BOUNDARIES,
    EvaluationConfig,
    EvaluationTarget,
    GenerationBinding,
    MechanisticJob,
    RubricRole,
    PreparedMechanisticEvaluation,
    _accept_predispatch_plan,
    _assert_accepted_job_plan,
    _engine_release_identity,
    _finite_score,
    _mechanistic_judgment_identity,
    _mechanistic_plan_entry,
    _model_route,
    _normalized_api_base,
    _rh_implementation_sha256,
    _stage_caps,
    _submission_content_sha256,
)
from rubric_gen.submission_revision.rh_output_store import RhOutputStore


@dataclass
class _GroupedRubrics:
    paths: dict[tuple[str, str], Path] = field(default_factory=dict)
    roles: dict[tuple[str, str], list[RubricRole]] = field(default_factory=dict)
    generation_bindings: dict[
        tuple[str, str],
        list[GenerationBinding],
    ] = field(default_factory=dict)

    def include(
        self,
        path: Path,
        model: str,
        *,
        role: RubricRole | None = None,
        generation_binding: GenerationBinding | None = None,
    ) -> None:
        resolved = path.resolve()
        rubric_sha256 = sha256_file(resolved)
        if (
            generation_binding is not None
            and generation_binding.rubric_sha256 != rubric_sha256
        ):
            raise RuntimeError("RH generation binding does not match its rubric")
        key = (rubric_sha256, model)
        self.paths.setdefault(key, resolved)
        self.roles.setdefault(key, [])
        self.generation_bindings.setdefault(key, [])
        if role is not None:
            self.roles[key].append(role)
        if (
            generation_binding is not None
            and generation_binding not in self.generation_bindings[key]
        ):
            self.generation_bindings[key].append(generation_binding)


class MechanisticEvaluationStage:
    def __init__(
        self,
        config: EvaluationConfig,
        targets: tuple[EvaluationTarget, ...],
    ) -> None:
        self.config = config
        self.targets = targets
        self.output = RhOutputStore(config.output_dir)
        self.root = self.output.root
        self._prepared: PreparedMechanisticEvaluation | None = None

    def preflight(self) -> None:
        """Prepare and cap all requests without output or provider calls."""

        if self._prepared is not None:
            return
        targets = self.targets
        jobs = self._jobs(targets)
        for job in jobs:
            _validate_mechanistic_job_bindings(job)
        unique_jobs_by_key: dict[str, MechanisticJob] = {}
        for job in jobs:
            unique_jobs_by_key.setdefault(job.key, job)
        unique_jobs = tuple(unique_jobs_by_key.values())
        self._prepared = PreparedMechanisticEvaluation(
            targets=targets,
            jobs=jobs,
            unique_jobs=unique_jobs,
            predispatch_plan=self._predispatch_plan(unique_jobs),
        )


    def _predispatch_plan(
        self,
        jobs: tuple[MechanisticJob, ...],
    ) -> dict[str, object]:
        benchmarks = {job.target.benchmark for job in jobs}
        if len(benchmarks) != 1:
            raise RuntimeError("RH mechanistic jobs must use one benchmark")
        planned_identities: list[dict[str, object]] = []

        with TerminalProgress(
            total=len(jobs),
            description="RH mechanistic planning",
            unit="judgment",
        ) as progress:
            def dispatches() -> Iterator[JudgeDispatchInput]:
                for job in jobs:
                    progress.set_status(job.target.assignment_id)
                    judge = self._judge_for_job(job)
                    if judge.scoring_identity() != job.grading_identity:
                        raise RuntimeError(
                            "RH mechanistic grading identity changed before "
                            "dispatch"
                        )
                    review_text, answer_text = judge.review_inputs(
                        job.submission
                    )
                    if (
                        sha256_text(review_text) != job.review_input_sha256
                        or sha256_text(answer_text) != job.answer_input_sha256
                    ):
                        raise RuntimeError(
                            "RH mechanistic request input changed before dispatch"
                        )
                    planned_identity = _mechanistic_plan_entry(
                        job=job,
                        judge=judge,
                        review_text=review_text,
                        answer_text=answer_text,
                        shape={},
                    )
                    planned_identity.pop("shape")
                    planned_identities.append(planned_identity)
                    progress.update()
                    yield JudgeDispatchInput(
                        rubric_text=judge.rubric.text,
                        review_text=review_text,
                        answer_text=answer_text,
                    )

            engine_plan = preflight_judge_dispatches(
                next(iter(benchmarks)),
                dispatches(),
            )
        raw_shapes = engine_plan.pop("jobs")
        if not isinstance(raw_shapes, list) or len(raw_shapes) != len(jobs):
            raise RuntimeError("RH mechanistic predispatch shapes are invalid")
        if len(planned_identities) != len(jobs):
            raise RuntimeError("RH mechanistic predispatch identities are invalid")
        planned_jobs = [
            {**identity, "shape": shape}
            for identity, shape in zip(
                planned_identities,
                raw_shapes,
                strict=True,
            )
        ]
        return _accept_predispatch_plan(
            stage="mechanistic",
            base=engine_plan,
            jobs=planned_jobs,
            outer_attempt_limit=JUDGE_MAX_ATTEMPTS,
            caps=_stage_caps(
                self.config.experiment.outcome_audit,
                "mechanistic",
            ),
        )


    def _jobs(
        self,
        targets: tuple[EvaluationTarget, ...],
    ) -> tuple[MechanisticJob, ...]:
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        implementation_sha256 = _rh_implementation_sha256()
        request_hashes: dict[tuple[str, str], tuple[str, str]] = {}
        return tuple(
            job
            for target in targets
            for boundary in BOUNDARIES
            for job in self._boundary_jobs(
                target,
                boundary,
                models,
                implementation_sha256,
                request_hashes,
            )
        )

    def _boundary_jobs(
        self,
        target: EvaluationTarget,
        boundary: str,
        models: tuple[str, ...],
        implementation_sha256: str,
        request_hashes: dict[tuple[str, str], tuple[str, str]],
    ) -> tuple[MechanisticJob, ...]:
        grouped = self._grouped_rubrics(target, boundary, models)
        jobs: list[MechanisticJob] = []
        for key in sorted(grouped.paths):
            rubric_path = grouped.paths[key]
            model = key[1]
            api_base = _normalized_api_base(
                self.config.vllm_endpoints.get(model)
            )
            judge = self._new_judge(
                target=target,
                model=model,
                api_base=api_base,
                rubric_path=rubric_path,
                artifact_key="predispatch-identity",
            )
            grading_identity = judge.scoring_identity()
            if set(grading_identity) != set(SCORING_IDENTITY_KEYS):
                raise RuntimeError(
                    "RH mechanistic grading identity fields changed"
                )
            request_key = (target.assignment_id, boundary)
            if request_key not in request_hashes:
                request_hashes[request_key] = self._request_hashes(
                    judge,
                    target.submission(boundary),
                )
            review_sha256, answer_sha256 = request_hashes[request_key]
            jobs.append(MechanisticJob(
                target=target,
                model=model,
                api_base=api_base,
                boundary=boundary,
                rubric_path=rubric_path,
                roles=tuple(sorted(
                    grouped.roles[key],
                    key=lambda value: (
                        value.name,
                        value.variant_index
                        if value.variant_index is not None
                        else -1,
                    ),
                )),
                generation_bindings=tuple(sorted(
                    grouped.generation_bindings[key],
                    key=lambda value: value.role,
                )),
                grading_identity=grading_identity,
                review_input_sha256=review_sha256,
                answer_input_sha256=answer_sha256,
                rh_implementation_sha256=implementation_sha256,
            ))
        return tuple(jobs)

    @staticmethod
    def _request_hashes(
        judge: RhAuditRubricJudge,
        submission: Path,
    ) -> tuple[str, str]:
        review_text, answer_text = judge.review_inputs(submission)
        return sha256_text(review_text), sha256_text(answer_text)

    @staticmethod
    def _grouped_rubrics(
        target: EvaluationTarget,
        boundary: str,
        models: tuple[str, ...],
    ) -> _GroupedRubrics:
        grouped = _GroupedRubrics()
        terminal = target.final_generation
        terminal_dir = target.final_manifest_path.parent
        terminal_models = tuple(dict.fromkeys((*models, target.weak_model)))
        path = terminal_dir / "rubric.txt"
        binding = _expected_generation_binding(
            target,
            boundary,
            "terminal_common",
        )
        for model in terminal_models:
            grouped.include(path, model, generation_binding=binding)

        active = target.generation(boundary)
        active_dir = target.generation_manifest_path(boundary).parent
        path = active_dir / "rubric.txt"
        binding = _expected_generation_binding(
            target,
            boundary,
            "active_local",
        )
        for model in models:
            grouped.include(path, model, generation_binding=binding)

        selected_role = RubricRole(
            "selected",
            target.selection.optimizer_index,
        )
        for model in models:
            grouped.include(
                target.selection.optimizer_path,
                model,
                role=selected_role,
            )
        return grouped

    def _run_job(self, job: MechanisticJob) -> dict[str, object]:
        _validate_mechanistic_job_bindings(job)
        record_name = f"{job.key}.json"
        self.output.ensure_directory("records")
        record_path = self.output.regular_file(
            "records",
            record_name,
            allow_missing=True,
        )
        self.output.ensure_directory("artifacts", job.key)
        self.output.validate_tree("artifacts", job.key)
        self.output.ensure_directory("artifacts", job.key, "evaluations")
        identity = _mechanistic_judgment_identity(job)
        judge = self._judge_for_job(job)
        if os.path.lexists(record_path):
            record = read_json_object(record_path, "RH mechanistic record")
            attempt_id = _mechanistic_attempt_id(job)
            artifacts = judge.validate(job.submission, attempt_id)
            self.output.validate_tree("artifacts", job.key)
            self.output.contained_regular_file(artifacts.score_validation_path)
            self.output.contained_regular_file(artifacts.evaluation_path)
            validation = read_json_object(
                artifacts.score_validation_path,
                "RH mechanistic score validation",
            )
            _validate_mechanistic_record(
                job=job,
                record=record,
                artifacts=artifacts,
                validation=validation,
            )
            return record
        attempt_id = _mechanistic_attempt_id(job)
        self._assert_current_dispatch(job, judge)
        artifacts = judge.evaluate(job.submission, attempt_id)
        self.output.validate_tree("artifacts", job.key)
        self.output.contained_regular_file(artifacts.score_validation_path)
        self.output.contained_regular_file(artifacts.evaluation_path)
        validation = read_json_object(
            artifacts.score_validation_path,
            "RH mechanistic score validation",
        )
        score = validation.get("score")
        normalized_score = _finite_score(score, "RH mechanistic judge score")
        observed_grading_identity = {
            key: validation.get(key) for key in SCORING_IDENTITY_KEYS
        }
        if observed_grading_identity != job.grading_identity:
            raise RuntimeError("RH mechanistic result grading identity changed")
        if (
            validation.get("review_input_sha256")
            != job.review_input_sha256
            or validation.get("answer_input_sha256")
            != job.answer_input_sha256
            or not isinstance(validation.get("engine_execution"), dict)
        ):
            raise RuntimeError("RH mechanistic result dispatch identity changed")
        record = {
            **identity,
            "score": normalized_score,
            "attempt_id": attempt_id,
            "validation_path": str(artifacts.score_validation_path),
            "evaluation_path": str(artifacts.evaluation_path),
            "engine_execution": validation["engine_execution"],
        }
        _validate_mechanistic_record(
            job=job,
            record=record,
            artifacts=artifacts,
            validation=validation,
        )
        self.output.write_json(("records", record_name), record)
        return record

    def _assert_current_dispatch(
        self,
        job: MechanisticJob,
        judge: RhAuditRubricJudge,
    ) -> None:
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("RH mechanistic dispatch has no accepted stage plan")
        review_text, answer_text = judge.review_inputs(job.submission)
        current_plan = preflight_judge_dispatches(
            job.target.benchmark,
            (JudgeDispatchInput(
                rubric_text=judge.rubric.text,
                review_text=review_text,
                answer_text=answer_text,
            ),),
        )
        shapes = current_plan.get("jobs")
        if not isinstance(shapes, list) or len(shapes) != 1:
            raise RuntimeError("RH mechanistic current dispatch shape is invalid")
        current = _mechanistic_plan_entry(
            job=job,
            judge=judge,
            review_text=review_text,
            answer_text=answer_text,
            shape=shapes[0],
        )
        _assert_accepted_job_plan(
            stage="mechanistic",
            plan=prepared.predispatch_plan,
            current=current,
        )

    def _judge_for_job(self, job: MechanisticJob) -> RhAuditRubricJudge:
        return self._new_judge(
            target=job.target,
            model=job.model,
            api_base=job.api_base,
            rubric_path=job.rubric_path,
            artifact_key=job.key,
        )

    def _new_judge(
        self,
        *,
        target: EvaluationTarget,
        model: str,
        api_base: str | None,
        rubric_path: Path,
        artifact_key: str,
    ) -> RhAuditRubricJudge:
        judge_config = SubmissionJudgeConfig(
            task_dir=target.task_dir,
            experiment_dir=self.output.path("artifacts", artifact_key),
            benchmark=target.benchmark,
            review=target.review,
            judge_model=model,
            base_url=api_base,
            rubric_name=None,
            rubric_set=None,
            rubric_path=rubric_path,
            max_review_chars=target.max_review_chars,
        )
        rubric = resolve_optimizer_rubric(judge_config)
        return RhAuditRubricJudge(judge_config, rubric)
def _mechanistic_job_identity(job: MechanisticJob) -> dict[str, object]:
    return {
        "assignment_id": job.target.assignment_id,
        "task_id": job.target.task_id,
        "replicate": job.target.replicate,
        "condition_id": job.target.condition_id,
        "model": job.model,
        "model_route": _model_route(job.api_base),
        "boundary": job.boundary,
        "submission_id": job.submission.name,
        "submission_content_sha256": _submission_content_sha256(
            job.submission
        ),
        "rubric_roles": [role.payload() for role in job.roles],
        "generation_bindings": [
            binding.payload() for binding in job.generation_bindings
        ],
        "rubric_path": str(job.rubric_path.resolve()),
        "rubric_sha256": sha256_file(job.rubric_path),
        "grading_identity": job.grading_identity,
        "review_input_sha256": job.review_input_sha256,
        "answer_input_sha256": job.answer_input_sha256,
        "engine_release_identity": _engine_release_identity(
            job.target.benchmark
        ),
        "rh_implementation_sha256": job.rh_implementation_sha256,
    }


def _mechanistic_assignment_reference_sha256(
    jobs: tuple[MechanisticJob, ...],
) -> str:
    digest = hashlib.sha256()
    for job in jobs:
        encoded = json.dumps(
            _mechanistic_job_identity(job),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()
def _mechanistic_attempt_id(job: MechanisticJob) -> str:
    return hashlib.sha256(
        ("rh-mechanistic\0" + job.key).encode()
    ).hexdigest()[:32]


def _validate_mechanistic_record(
    *,
    job: MechanisticJob,
    record: dict[str, object],
    artifacts: JudgeArtifacts,
    validation: dict[str, object],
) -> None:
    identity = _mechanistic_judgment_identity(job)
    result_keys = {
        "score",
        "attempt_id",
        "validation_path",
        "evaluation_path",
        "engine_execution",
    }
    if set(record) != set(identity) | result_keys:
        raise RuntimeError("RH mechanistic record fields changed")
    if any(record[key] != value for key, value in identity.items()):
        raise RuntimeError("RH mechanistic record identity changed")
    if record["attempt_id"] != _mechanistic_attempt_id(job):
        raise RuntimeError("RH mechanistic record attempt ID changed")
    if (
        record["validation_path"] != str(artifacts.score_validation_path)
        or record["evaluation_path"] != str(artifacts.evaluation_path)
    ):
        raise RuntimeError("RH mechanistic record artifact path changed")
    score = _finite_score(record["score"], "RH mechanistic record score")
    validation_score = _finite_score(
        validation.get("score"),
        "RH mechanistic validation score",
    )
    if score != validation_score:
        raise RuntimeError("RH mechanistic record score changed")
    observed_grading_identity = {
        key: validation.get(key) for key in SCORING_IDENTITY_KEYS
    }
    if observed_grading_identity != job.grading_identity:
        raise RuntimeError("RH mechanistic validation identity changed")
    engine_execution = validation.get("engine_execution")
    if (
        validation.get("review_input_sha256") != job.review_input_sha256
        or validation.get("answer_input_sha256") != job.answer_input_sha256
        or type(engine_execution) is not dict
        or record["engine_execution"] != engine_execution
    ):
        raise RuntimeError("RH mechanistic validation dispatch identity changed")



def _score_panel(
    observations: dict[tuple[str, int | None, str, str], float],
    role: str,
    variant_index: int | None,
    boundary: str,
    models: tuple[str, ...],
) -> dict[str, object]:
    scores = {
        model: observations[(role, variant_index, boundary, model)]
        for model in models
    }
    values = list(scores.values())
    return {
        "scores": scores,
        "mean": fmean(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _expected_generation_binding(
    target: EvaluationTarget,
    boundary: str,
    role: str,
) -> GenerationBinding:
    if role == "terminal_common":
        generation = target.final_generation
        manifest_path = target.final_manifest_path
        manifest_sha256 = target.final_manifest_sha256
    elif role == "active_local":
        generation = target.generation(boundary)
        manifest_path = target.generation_manifest_path(boundary)
        manifest_sha256 = target.generation_manifest_sha256(boundary)
    else:
        raise ValueError(f"invalid RH generation role: {role}")
    return GenerationBinding(
        role=role,
        generation_round=generation.generation_round,
        generation_sha256=generation.generation_sha256,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        rubric_sha256=generation.rubric.content_sha256,
    )


def _validate_mechanistic_job_bindings(job: MechanisticJob) -> None:
    rubric_sha256 = sha256_file(job.rubric_path)
    for binding in job.generation_bindings:
        if binding.role == "terminal_common":
            generation = job.target.final_generation
        elif binding.role == "active_local":
            generation = job.target.generation(job.boundary)
        else:
            raise RuntimeError("RH generation binding has an invalid role")
        if generation.rubric.content_sha256 != rubric_sha256:
            raise RuntimeError("RH generation binding has the wrong rubric")
        if binding != _expected_generation_binding(
            job.target,
            job.boundary,
            binding.role,
        ):
            raise RuntimeError("RH generation binding changed")
        if sha256_file(binding.manifest_path) != binding.manifest_sha256:
            raise RuntimeError("RH generation manifest changed")


def _generation_score_panel(
    target: EvaluationTarget,
    boundary: str,
    role: str,
    observations: dict[tuple[str, str, str, str], float],
    models: tuple[str, ...],
) -> dict[str, object]:
    if role == "terminal_common":
        generation = target.final_generation
        manifest_path = target.final_manifest_path
        manifest_sha256 = target.final_manifest_sha256
    elif role == "active_local":
        generation = target.generation(boundary)
        manifest_path = target.generation_manifest_path(boundary)
        manifest_sha256 = target.generation_manifest_sha256(boundary)
    else:
        raise ValueError(f"invalid RH generation role: {role}")
    rubric_sha256 = generation.rubric.content_sha256
    scores = {
        model: observations[(role, boundary, model, rubric_sha256)]
        for model in models
    }
    values = list(scores.values())
    return {
        "role": role,
        "generation_round": generation.generation_round,
        "source_boundary": generation.source_boundary,
        "proposer_call_budget": generation.proposer_call_budget,
        "generation_sha256": generation.generation_sha256,
        "rubric_sha256": rubric_sha256,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "scores": scores,
        "mean": fmean(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
    }
