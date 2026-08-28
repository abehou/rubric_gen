"""Run strong-ensemble rescoring against each original human rubric."""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from numbers import Real
from pathlib import Path
from typing import Iterator

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.judge import (
    JUDGE_MAX_ATTEMPTS,
    SCORING_IDENTITY_KEYS,
    JudgeArtifacts,
)
from rubric_gen.submission_revision.judging.preflight import (
    JudgeDispatchInput,
    preflight_judge_dispatches,
)
from rubric_gen.submission_revision.original_rubric_inputs import (
    BOUNDARIES,
    SUMMARY_KIND,
    JobOperation,
    JudgeFactory,
    OriginalRubricEnsembleConfig,
    OriginalRubricJob,
    OriginalRubricStudy,
    PreparedOriginalRubricJob,
    StudyLoader,
    build_original_rubric_judge,
    is_sha256,
    load_completed_original_rubric_study,
    original_rubric_attempt_id,
    validated_scoring_identity,
)
from rubric_gen.submission_revision import original_rubric_summary


def _prepare_job(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
    build_judge: JudgeFactory,
) -> PreparedOriginalRubricJob:
    judge = build_judge(config, job)
    scoring_identity = validated_scoring_identity(judge, job)
    if (
        judge.rubric.sha256 != job.target.rubric_sha256
        or sha256_text(judge.rubric.text) != job.target.rubric_sha256
    ):
        raise RuntimeError("original-rubric text changed before predispatch")
    review_text, answer_text = judge.review_inputs(job.submission)
    return _prepared_job_from_request(
        job,
        scoring_identity,
        review_text,
        answer_text,
    )


def _prepared_job_from_request(
    job: OriginalRubricJob,
    scoring_identity: dict[str, object],
    review_text: str,
    answer_text: str,
) -> PreparedOriginalRubricJob:
    review_input_sha256 = sha256_text(review_text)
    answer_input_sha256 = sha256_text(answer_text)
    semantic_identity = {
        "task_id": job.target.task_id,
        "requested_model": job.model,
        "rubric_text_sha256": job.target.rubric_sha256,
        "review_input_sha256": review_input_sha256,
        "answer_input_sha256": answer_input_sha256,
        "scoring_identity": scoring_identity,
    }
    semantic_judgment_id = sha256_text(json.dumps(
        semantic_identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ))
    return PreparedOriginalRubricJob(
        job=job,
        semantic_judgment_id=semantic_judgment_id,
        scoring_identity=scoring_identity,
        rubric_text_sha256=job.target.rubric_sha256,
        review_input_sha256=review_input_sha256,
        answer_input_sha256=answer_input_sha256,
    )


def _dispatch_input(
    config: OriginalRubricEnsembleConfig,
    prepared: PreparedOriginalRubricJob,
    build_judge: JudgeFactory,
) -> JudgeDispatchInput:
    judge = build_judge(config, prepared.job)
    scoring_identity = validated_scoring_identity(judge, prepared.job)
    if (
        judge.rubric.sha256 != prepared.rubric_text_sha256
        or sha256_text(judge.rubric.text) != prepared.rubric_text_sha256
    ):
        raise RuntimeError("original-rubric text changed during predispatch")
    review_text, answer_text = judge.review_inputs(prepared.job.submission)
    observed = _prepared_job_from_request(
        prepared.job,
        scoring_identity,
        review_text,
        answer_text,
    )
    if observed != prepared:
        raise RuntimeError("original-rubric request changed during predispatch")
    return JudgeDispatchInput(
        rubric_text=judge.rubric.text,
        review_text=review_text,
        answer_text=answer_text,
    )


def _job_sort_key(job: OriginalRubricJob) -> tuple[str, int, int]:
    return (
        job.target.assignment_id,
        PRIMARY_RH_MODELS.index(job.model),
        BOUNDARIES.index(job.boundary),
    )


def _group_prepared_jobs(
    prepared_jobs: tuple[PreparedOriginalRubricJob, ...],
) -> dict[str, tuple[PreparedOriginalRubricJob, ...]]:
    grouped: dict[str, list[PreparedOriginalRubricJob]] = {}
    for prepared in prepared_jobs:
        grouped.setdefault(prepared.semantic_judgment_id, []).append(prepared)
    return {
        semantic_id: tuple(sorted(values, key=lambda value: _job_sort_key(value.job)))
        for semantic_id, values in sorted(grouped.items())
    }


def _judgment_owner(job: OriginalRubricJob) -> dict[str, str]:
    return {
        "assignment_id": job.target.assignment_id,
        "model": job.model,
        "boundary": job.boundary,
    }


def _relative_artifact(output_dir: Path, path: Path) -> str:
    resolved_output = output_dir.resolve()
    resolved_path = path.resolve()
    try:
        relative = resolved_path.relative_to(resolved_output)
    except ValueError as exc:
        raise RuntimeError(f"judge artifact escaped the output directory: {path}") from exc
    return relative.as_posix()


def _job_identity(job: OriginalRubricJob) -> dict[str, object]:
    return {
        "assignment_id": job.target.assignment_id,
        "task_id": job.target.task_id,
        "replicate": job.target.replicate,
        "condition_id": job.target.condition_id,
        "experiment": str(job.target.experiment_dir),
        "model": job.model,
        "boundary": job.boundary,
        "submission_id": job.submission.name,
        "rubric_sha256": job.target.rubric_sha256,
        "attempt_id": original_rubric_attempt_id(job),
    }


def _completed_record(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
    artifacts: JudgeArtifacts,
) -> dict[str, object]:
    validation = read_json_object(
        artifacts.score_validation_path,
        "ensemble score validation",
    )
    score = validation.get("score")
    scoring_identity = {
        key: validation.get(key) for key in SCORING_IDENTITY_KEYS
    }
    review_input_sha256 = validation.get("review_input_sha256")
    answer_input_sha256 = validation.get("answer_input_sha256")
    if (
        isinstance(score, bool)
        or not isinstance(score, Real)
        or not math.isfinite(float(score))
        or not 0 <= float(score) <= 100
        or validation.get("effective_judge_model") != job.model
        or validation.get("rendered_rubric_sha256") != job.target.rubric_sha256
        or validation.get("review_mode") != job.target.review
        or not is_sha256(review_input_sha256)
        or not is_sha256(answer_input_sha256)
    ):
        raise RuntimeError("ensemble judge produced an incompatible score validation")
    usage_path = artifacts.score_validation_path.with_name("usage.json")
    for path in (artifacts.score_validation_path, artifacts.evaluation_path, usage_path):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"ensemble judge artifact is missing: {path}")
    return {
        **_job_identity(job),
        "status": "completed",
        "score": float(score),
        "scoring_identity": scoring_identity,
        "review_input_sha256": review_input_sha256,
        "answer_input_sha256": answer_input_sha256,
        "score_validation": _relative_artifact(
            config.output_dir,
            artifacts.score_validation_path,
        ),
        "score_validation_sha256": sha256_file(artifacts.score_validation_path),
        "evaluation": _relative_artifact(config.output_dir, artifacts.evaluation_path),
        "evaluation_sha256": sha256_file(artifacts.evaluation_path),
        "usage": _relative_artifact(config.output_dir, usage_path),
        "usage_sha256": sha256_file(usage_path),
    }


def _completed_reference_record(
    completed: dict[str, object],
    prepared: PreparedOriginalRubricJob,
    owner: OriginalRubricJob,
) -> dict[str, object]:
    return {
        **_job_identity(prepared.job),
        "semantic_judgment_id": prepared.semantic_judgment_id,
        "judgment_owner": _judgment_owner(owner),
        "artifact_attempt_id": original_rubric_attempt_id(owner),
        "status": "completed",
        "score": completed["score"],
        "score_validation": completed["score_validation"],
        "score_validation_sha256": completed["score_validation_sha256"],
        "evaluation": completed["evaluation"],
        "evaluation_sha256": completed["evaluation_sha256"],
        "usage": completed["usage"],
        "usage_sha256": completed["usage_sha256"],
    }


def _failed_reference_record(
    prepared: PreparedOriginalRubricJob,
    owner: OriginalRubricJob,
    error: Exception,
) -> dict[str, object]:
    message = str(error) or type(error).__name__
    return {
        **_job_identity(prepared.job),
        "semantic_judgment_id": prepared.semantic_judgment_id,
        "judgment_owner": _judgment_owner(owner),
        "artifact_attempt_id": original_rubric_attempt_id(owner),
        "status": "failed",
        "error": message,
    }


def _evaluate_job(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> dict[str, object]:
    judge = build_original_rubric_judge(config, job)
    artifacts = judge.evaluate(job.submission, original_rubric_attempt_id(job))
    return _completed_record(config, job, artifacts)


def _validate_job(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> dict[str, object]:
    judge = build_original_rubric_judge(config, job)
    artifacts = judge.validate(job.submission, original_rubric_attempt_id(job))
    return _completed_record(config, job, artifacts)


def _path_contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


class OriginalRubricEnsembleRunner:
    def __init__(
        self,
        config: OriginalRubricEnsembleConfig,
        *,
        load_study: StudyLoader = load_completed_original_rubric_study,
        evaluate_job: JobOperation = _evaluate_job,
        validate_job: JobOperation = _validate_job,
        build_judge: JudgeFactory = build_original_rubric_judge,
    ) -> None:
        self.config = config
        self.load_study = load_study
        self.evaluate_job = evaluate_job
        self.validate_job = validate_job
        self.build_judge = build_judge

    def run(self) -> int:
        study_path = self.config.study_dir.resolve()
        output_path = self.config.output_dir.resolve()
        if _path_contains(study_path, output_path) or _path_contains(
            output_path, study_path
        ):
            raise ValueError("judge output and source study must not contain each other")
        output_state = self._inspect_output()
        study = self.load_study(study_path)
        jobs = self._jobs(study)
        prepared_jobs = tuple(
            _prepare_job(self.config, job, self.build_judge) for job in jobs
        )
        groups = _group_prepared_jobs(prepared_jobs)
        predispatch_plan = self._predispatch_plan(study, groups)
        self._create_output(output_state)
        retained = (
            self._retained_records(
                study,
                jobs,
                groups,
                predispatch_plan,
            )
            if self.config.resume and output_state[1]
            else []
        )
        records = list(retained)
        self._write_summary(
            study,
            records,
            predispatch_plan=predispatch_plan,
            semantic_judgment_count=len(groups),
            final=False,
        )
        self._execute_pending_groups(
            study,
            jobs,
            groups,
            self._pending_groups(groups, retained),
            records,
            predispatch_plan,
        )
        self._write_summary(
            study,
            records,
            predispatch_plan=predispatch_plan,
            semantic_judgment_count=len(groups),
            final=True,
        )
        return int(any(record["status"] == "failed" for record in records))

    @staticmethod
    def _jobs(study: OriginalRubricStudy) -> tuple[OriginalRubricJob, ...]:
        return tuple(
            OriginalRubricJob(target, model, boundary)
            for target in study.targets
            for model in PRIMARY_RH_MODELS
            for boundary in BOUNDARIES
        )

    @staticmethod
    def _pending_groups(
        groups: dict[str, tuple[PreparedOriginalRubricJob, ...]],
        retained: list[dict[str, object]],
    ) -> list[tuple[PreparedOriginalRubricJob, ...]]:
        retained_keys = {
            original_rubric_summary.record_key(record) for record in retained
        }
        pending: list[tuple[PreparedOriginalRubricJob, ...]] = []
        for group in groups.values():
            present = [item.job.key in retained_keys for item in group]
            if any(present) and not all(present):
                raise RuntimeError(
                    "judge resume summary contains a partial semantic judgment"
                )
            if not any(present):
                pending.append(group)
        return pending

    def _execute_pending_groups(
        self,
        study: OriginalRubricStudy,
        jobs: tuple[OriginalRubricJob, ...],
        groups: dict[str, tuple[PreparedOriginalRubricJob, ...]],
        pending_groups: list[tuple[PreparedOriginalRubricJob, ...]],
        records: list[dict[str, object]],
        predispatch_plan: dict[str, object],
    ) -> None:
        with TerminalProgress(
            total=len(jobs),
            description="original-rubric ensemble judging",
            unit="judgment",
        ) as progress:
            for _record in records:
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {
                    pool.submit(
                        self._evaluate_prepared_group,
                        group,
                    ): group
                    for group in pending_groups
                }
                for future in as_completed(futures):
                    group = futures[future]
                    try:
                        completed = future.result()
                        new_records = self._completed_group_records(completed, group)
                    except Exception as exc:
                        owner = group[0].job
                        new_records = [
                            _failed_reference_record(item, owner, exc)
                            for item in group
                        ]
                    records.extend(new_records)
                    self._write_summary(
                        study,
                        records,
                        predispatch_plan=predispatch_plan,
                        semantic_judgment_count=len(groups),
                        final=False,
                    )
                    for _record in new_records:
                        progress.update()
                    progress.set_status(
                        f"failed={sum(item['status'] == 'failed' for item in records)}"
                    )

    def _completed_group_records(
        self,
        completed: dict[str, object],
        group: tuple[PreparedOriginalRubricJob, ...],
    ) -> list[dict[str, object]]:
        self._check_base_completed_record(completed, group[0])
        owner = group[0].job
        return [
            _completed_reference_record(completed, item, owner)
            for item in group
        ]

    def _inspect_output(
        self,
    ) -> tuple[bool, bool, tuple[int, int] | None]:
        output = self.config.output_dir
        if output.is_symlink() or output.exists() and not output.is_dir():
            raise ValueError(f"judge output must be a regular directory: {output}")
        if output.is_dir():
            entries = list(output.iterdir())
            if entries and not self.config.resume:
                raise FileExistsError(
                    f"judge output is not empty; use --resume: {output}"
                )
            if entries and not (output / "summary.json").is_file():
                raise RuntimeError("judge resume output has no summary.json")
        exists = output.is_dir()
        identity = None
        if exists:
            status = output.stat(follow_symlinks=False)
            identity = status.st_dev, status.st_ino
        return exists, (output / "summary.json").is_file(), identity

    def _create_output(
        self,
        expected_state: tuple[bool, bool, tuple[int, int] | None],
    ) -> None:
        output = self.config.output_dir
        if output.is_symlink() or output.exists() and not output.is_dir():
            raise ValueError(f"judge output must be a regular directory: {output}")
        expected_exists, expected_summary, expected_identity = expected_state
        if expected_exists:
            if not output.is_dir():
                raise RuntimeError("judge output changed during predispatch")
            status = output.stat(follow_symlinks=False)
            if (status.st_dev, status.st_ino) != expected_identity:
                raise RuntimeError("judge output changed during predispatch")
            entries = list(output.iterdir())
            if (
                (output / "summary.json").is_file() != expected_summary
                or entries and not expected_summary
            ):
                raise RuntimeError("judge output changed during predispatch")
            return
        if output.exists():
            raise RuntimeError("judge output appeared during predispatch")
        output.mkdir(parents=True, exist_ok=False)

    def _evaluate_prepared_group(
        self,
        group: tuple[PreparedOriginalRubricJob, ...],
    ) -> dict[str, object]:
        for prepared in group:
            observed = _prepare_job(
                self.config,
                prepared.job,
                self.build_judge,
            )
            if observed != prepared:
                raise RuntimeError(
                    "original-rubric request changed before provider dispatch"
                )
        return self.evaluate_job(self.config, group[0].job)

    def _predispatch_plan(
        self,
        study: OriginalRubricStudy,
        groups: dict[str, tuple[PreparedOriginalRubricJob, ...]],
    ) -> dict[str, object]:
        def dispatches() -> Iterator[JudgeDispatchInput]:
            for group in groups.values():
                first: JudgeDispatchInput | None = None
                for prepared in group:
                    observed = _dispatch_input(
                        self.config,
                        prepared,
                        self.build_judge,
                    )
                    if first is None:
                        first = observed
                    elif observed != first:
                        raise RuntimeError(
                            "deduplicated original-rubric requests differ"
                        )
                assert first is not None
                yield first

        benchmark = study.targets[0].benchmark
        base = preflight_judge_dispatches(benchmark, dispatches())
        raw_shapes = base.pop("jobs")
        if type(raw_shapes) is not list or len(raw_shapes) != len(groups):
            raise RuntimeError("original-rubric predispatch shapes are invalid")
        planned_jobs = []
        for group, shape in zip(groups.values(), raw_shapes, strict=True):
            owner = group[0]
            planned_jobs.append({
                "semantic_judgment_id": owner.semantic_judgment_id,
                "logical_reference_count": len(group),
                "judgment_owner": _judgment_owner(owner.job),
                "task_id": owner.job.target.task_id,
                "requested_model": owner.job.model,
                "rubric_text_sha256": owner.rubric_text_sha256,
                "review_input_sha256": owner.review_input_sha256,
                "answer_input_sha256": owner.answer_input_sha256,
                "scoring_identity": owner.scoring_identity,
                "shape": shape,
            })
        outer_attempt_limit = JUDGE_MAX_ATTEMPTS
        caps = {
            "calls": study.mechanistic_max_calls,
            "request_bytes": study.mechanistic_max_request_bytes,
            "output_tokens": study.mechanistic_max_output_tokens,
        }
        base_totals: dict[str, int] = {}
        maximum_totals: dict[str, int] = {}
        for resource in ("calls", "request_bytes", "output_tokens"):
            value = base.get(resource)
            if type(value) is not int or value < 0:
                raise RuntimeError(
                    f"original-rubric predispatch {resource} is invalid"
                )
            base_totals[resource] = value
            maximum_totals[resource] = value * outer_attempt_limit
            if maximum_totals[resource] > caps[resource]:
                raise RuntimeError(
                    "original-rubric predispatch "
                    f"{resource} exceeds its hard cap: "
                    f"{maximum_totals[resource]} > {caps[resource]}"
                )
        return {
            "stage": "original-rubric-mechanistic",
            "accepted": True,
            "outer_attempt_limit": outer_attempt_limit,
            "caps": caps,
            "base_totals": base_totals,
            "maximum_totals": maximum_totals,
            "request_byte_measurement": base["request_byte_measurement"],
            "dispatch_count": base["dispatch_count"],
            "logical_reference_count": sum(len(group) for group in groups.values()),
            "grading_engine": base["grading_engine"],
            "benchmark": base["benchmark"],
            "largest_request_bytes_per_call": base[
                "largest_request_bytes_per_call"
            ],
            "jobs": planned_jobs,
        }

    def _protocol(self) -> dict[str, object]:
        return {
            "models": list(PRIMARY_RH_MODELS),
            "submissions": list(BOUNDARIES),
            "rubric": "original-human-written-r0000",
            "score_scale": [0, 100],
            "numeric_aggregates": ["mean", "median"],
            "direction_aggregate": "strict-majority-of-model-deltas",
            "semantic_deduplication": (
                "task-request-rubric-model-route-engine-implementation"
            ),
            "max_attempts": JUDGE_MAX_ATTEMPTS,
        }

    def _retained_records(
        self,
        study: OriginalRubricStudy,
        jobs: tuple[OriginalRubricJob, ...],
        groups: dict[str, tuple[PreparedOriginalRubricJob, ...]],
        predispatch_plan: dict[str, object],
    ) -> list[dict[str, object]]:
        summary = self._resume_summary(study, predispatch_plan)
        grouped = self._group_resume_records(summary, jobs, groups)
        retained: list[dict[str, object]] = []
        for semantic_id, values in grouped.items():
            retained.extend(self._retained_group(groups[semantic_id], values))
        return retained

    def _resume_summary(
        self,
        study: OriginalRubricStudy,
        predispatch_plan: dict[str, object],
    ) -> dict[str, object]:
        summary = read_json_object(
            self.config.output_dir / "summary.json",
            "original-rubric judge summary",
        )
        if (
            set(summary) != {
                "kind",
                "status",
                "source",
                "protocol",
                "predispatch_plan",
                "totals",
                "records",
                "assignments",
                "conditions",
            }
            or summary.get("kind") != SUMMARY_KIND
            or summary.get("source") != {
                "study_dir": str(study.source),
                "experiment_id": study.experiment_id,
                "assignment_count": len(study.targets),
            }
            or summary.get("protocol") != self._protocol()
            or summary.get("predispatch_plan") != predispatch_plan
            or type(summary.get("records")) is not list
        ):
            raise RuntimeError("judge resume summary has incompatible identity")
        return summary

    def _group_resume_records(
        self,
        summary: dict[str, object],
        jobs: tuple[OriginalRubricJob, ...],
        groups: dict[str, tuple[PreparedOriginalRubricJob, ...]],
    ) -> dict[str, list[dict[str, object]]]:
        job_keys = {job.key for job in jobs}
        prepared_by_key = {
            prepared.job.key: prepared
            for group in groups.values()
            for prepared in group
        }
        values_by_semantic_id: dict[str, list[dict[str, object]]] = {}
        seen: set[tuple[str, str, str]] = set()
        records = summary["records"]
        assert isinstance(records, list)
        with TerminalProgress(
            total=len(records),
            description="validating resumed judgments",
            unit="judgment",
        ) as progress:
            for value in records:
                if type(value) is not dict:
                    raise RuntimeError(
                        "judge resume summary contains a non-object record"
                    )
                key = original_rubric_summary.record_key(value)
                if key in seen or key not in job_keys:
                    raise RuntimeError(
                        "judge resume summary contains an invalid job identity"
                    )
                seen.add(key)
                prepared = prepared_by_key[key]
                owner = groups[prepared.semantic_judgment_id][0].job
                if not self._has_reference_identity(value, prepared, owner):
                    raise RuntimeError(
                        "judge resume summary contains an invalid semantic reference"
                    )
                if value.get("status") not in {"failed", "completed"}:
                    raise RuntimeError(
                        "judge resume summary contains an invalid status"
                    )
                progress.update()
                values_by_semantic_id.setdefault(
                    prepared.semantic_judgment_id,
                    [],
                ).append(value)
        return values_by_semantic_id

    def _retained_group(
        self,
        group: tuple[PreparedOriginalRubricJob, ...],
        values: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        expected_keys = {prepared.job.key for prepared in group}
        if {
            original_rubric_summary.record_key(value) for value in values
        } != expected_keys:
            raise RuntimeError(
                "judge resume summary contains a partial semantic judgment"
            )
        statuses = {value.get("status") for value in values}
        if statuses == {"failed"}:
            return []
        if statuses != {"completed"}:
            raise RuntimeError(
                "judge resume semantic judgment has inconsistent statuses"
            )
        owner = group[0].job
        validated = self.validate_job(self.config, owner)
        self._check_base_completed_record(validated, group[0])
        expected_values = {
            item.job.key: _completed_reference_record(validated, item, owner)
            for item in group
        }
        for value in values:
            if expected_values[original_rubric_summary.record_key(value)] != value:
                raise RuntimeError(
                    "judge resume record differs from its sealed artifacts"
                )
        return values

    @staticmethod
    def _check_base_completed_record(
        record: dict[str, object],
        prepared: PreparedOriginalRubricJob,
    ) -> None:
        job = prepared.job
        if (
            record.get("status") != "completed"
            or original_rubric_summary.record_key(record) != job.key
            or isinstance(record.get("score"), bool)
            or not isinstance(record.get("score"), Real)
            or not math.isfinite(float(record["score"]))
            or not 0 <= float(record["score"]) <= 100
            or record.get("scoring_identity") != prepared.scoring_identity
            or record.get("review_input_sha256")
            != prepared.review_input_sha256
            or record.get("answer_input_sha256")
            != prepared.answer_input_sha256
            or any(
                type(record.get(key)) is not str or not record[key]
                for key in (
                    "score_validation",
                    "score_validation_sha256",
                    "evaluation",
                    "evaluation_sha256",
                    "usage",
                    "usage_sha256",
                )
            )
        ):
            raise RuntimeError("ensemble evaluator returned an invalid completed record")

    @staticmethod
    def _has_reference_identity(
        record: dict[str, object],
        prepared: PreparedOriginalRubricJob,
        owner: OriginalRubricJob,
    ) -> bool:
        common = {
            **_job_identity(prepared.job),
            "semantic_judgment_id": prepared.semantic_judgment_id,
            "judgment_owner": _judgment_owner(owner),
            "artifact_attempt_id": original_rubric_attempt_id(owner),
        }
        if any(record.get(key) != value for key, value in common.items()):
            return False
        if record.get("status") == "failed":
            return (
                set(record) == set(common) | {"status", "error"}
                and type(record.get("error")) is str
                and bool(record["error"])
            )
        completed_fields = {
            "status",
            "score",
            "score_validation",
            "score_validation_sha256",
            "evaluation",
            "evaluation_sha256",
            "usage",
            "usage_sha256",
        }
        return set(record) == set(common) | completed_fields

    def _write_summary(
        self,
        study: OriginalRubricStudy,
        records: list[dict[str, object]],
        *,
        predispatch_plan: dict[str, object],
        semantic_judgment_count: int,
        final: bool,
    ) -> None:
        records.sort(key=original_rubric_summary.record_sort_key)
        assignment_summaries = original_rubric_summary.assignment_summaries(
            study,
            records,
        )
        complete = sum(record["status"] == "completed" for record in records)
        failed = sum(record["status"] == "failed" for record in records)
        total = len(study.targets) * len(PRIMARY_RH_MODELS) * len(BOUNDARIES)
        status = (
            "completed"
            if complete == total
            else "failed"
            if final
            else "running"
        )
        write_json_atomic(
            self.config.output_dir / "summary.json",
            {
                "kind": SUMMARY_KIND,
                "status": status,
                "source": {
                    "study_dir": str(study.source),
                    "experiment_id": study.experiment_id,
                    "assignment_count": len(study.targets),
                },
                "protocol": self._protocol(),
                "predispatch_plan": predispatch_plan,
                "totals": {
                    "jobs": total,
                    "semantic_judgments": semantic_judgment_count,
                    "completed": complete,
                    "failed": failed,
                    "pending": total - complete - failed,
                },
                "records": records,
                "assignments": assignment_summaries,
                "conditions": original_rubric_summary.condition_summaries(
                    assignment_summaries
                ),
            },
        )
