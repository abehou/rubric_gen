"""Run RH outcome scoring with every stage-complete strong judge."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision import rh_protocol as rh
from rubric_gen.submission_revision import rh_rubric_free_evaluation as rubric_free_evaluation
from rubric_gen.submission_revision import rh_rubric_score as rubric_score
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.rh_output_store import RhOutputStore


PANEL_POLICY: dict[str, object] = {
    "aggregation": "arithmetic-mean-over-stage-complete-judges",
    "minimum_stage_complete_judges": 1,
    "configured_judge_failure_scope": "whole-stage",
}


def _is_judge_failure(error: BaseException, prefix: str) -> bool:
    return isinstance(error, RuntimeError) and str(error).startswith(prefix)


def _failure_record(
    *,
    key: str,
    model: str,
    error: BaseException,
    instrument: str | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "judgment_key": key,
        "model": model,
        "reason": "judge-failed",
        "error_type": type(error).__name__,
    }
    if instrument is not None:
        record["instrument"] = instrument
    return record


def _prior_failures(
    output: RhOutputStore,
    *,
    expected_kind: str,
    instruments: frozenset[str] | None = None,
) -> dict[str, dict[str, object]]:
    summary_path = output.regular_file("summary.json", allow_missing=True)
    if not os.path.lexists(summary_path):
        return {}
    try:
        summary = read_json_object(summary_path, "RH outcome summary")
    except RuntimeError:
        summary_path.unlink()
        return {}
    failures = summary.get("judge_failures")
    if (
        summary.get("kind") != expected_kind
        or summary.get("status") != "completed"
        or summary.get("panel_policy") != PANEL_POLICY
        or not isinstance(failures, list)
    ):
        summary_path.unlink()
        return {}
    result: dict[str, dict[str, object]] = {}
    expected_fields = {"judgment_key", "model", "reason", "error_type"}
    if instruments is not None:
        expected_fields.add("instrument")
    for failure in failures:
        if (
            not isinstance(failure, dict)
            or set(failure) != expected_fields
            or type(failure.get("judgment_key")) is not str
            or type(failure.get("model")) is not str
            or failure.get("reason") != "judge-failed"
            or type(failure.get("error_type")) is not str
            or (
                instruments is not None
                and failure.get("instrument") not in instruments
            )
        ):
            raise RuntimeError("RH outcome judge failure record is invalid")
        key = str(failure["judgment_key"])
        if key in result:
            raise RuntimeError("RH outcome judge failure is duplicated")
        result[key] = failure
    return result


@dataclass
class _RubricScoreObservations:
    rubrics: dict[tuple[str, int | None, str, str], float] = field(
        default_factory=dict
    )
    generations: dict[tuple[str, str, str, str], float] = field(
        default_factory=dict
    )


def _store_unique(
    observations: dict[tuple[object, ...], float],
    key: tuple[object, ...],
    score: float,
    label: str,
) -> None:
    if key in observations:
        raise RuntimeError(f"duplicate RH {label} observation: {key}")
    observations[key] = score


def _rubric_score_record_context(
    record: dict[str, object],
) -> tuple[str, str, float, str]:
    artifact = str(record["artifact"])
    model = str(record["model"])
    score = rh._finite_score(record.get("score"), "RH rubric score score")
    rubric_sha256 = record.get("rubric_sha256")
    if not rh._is_sha256(rubric_sha256):
        raise RuntimeError("RH rubric score record has an invalid rubric hash")
    return artifact, model, score, str(rubric_sha256)


def _collect_generation_observations(
    target: rh.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _RubricScoreObservations,
) -> None:
    artifact, model, score, rubric_sha256 = context
    bindings = record.get("generation_bindings")
    if not isinstance(bindings, list):
        raise RuntimeError("RH generation bindings are invalid")
    for binding in bindings:
        if not isinstance(binding, dict):
            raise RuntimeError("RH generation binding is invalid")
        role = binding.get("role")
        if role == "active_local":
            generation = target.generation(artifact)
        else:
            raise RuntimeError("RH generation binding has an invalid role")
        if generation.rubric.content_sha256 != rubric_sha256:
            raise RuntimeError("RH generation binding has the wrong rubric")
        expected = rubric_score._expected_generation_binding(
            target,
            artifact,
            str(role),
        ).payload()
        if binding != expected:
            raise RuntimeError("RH generation binding changed")
        _store_unique(
            observations.generations,
            (str(role), artifact, model, rubric_sha256),
            score,
            "generation",
        )


def _collect_rubric_role_observations(
    target: rh.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _RubricScoreObservations,
) -> None:
    artifact, model, score, rubric_sha256 = context
    roles = record.get("rubric_roles")
    if not isinstance(roles, list):
        raise RuntimeError("RH rubric score record has no rubric roles")
    for role in roles:
        if role == {"name": "original", "variant_index": None}:
            expected_sha256 = target.selection.master_sha256
        elif role == {
            "name": "selected",
            "variant_index": target.selection.optimizer_index,
        }:
            expected_sha256 = target.selection.optimizer_sha256
        else:
            raise RuntimeError(
                "RH rubric score rubric role does not match the judged rubric"
            )
        if rubric_sha256 != expected_sha256:
            raise RuntimeError(
                "RH rubric score rubric role does not match the judged rubric"
            )
        _store_unique(
            observations.rubrics,
            (str(role["name"]), role["variant_index"], artifact, model),
            score,
            "rubric_score",
        )


def _collect_rubric_score_observations(
    target: rh.EvaluationTarget,
    records: list[dict[str, object]],
) -> _RubricScoreObservations:
    observations = _RubricScoreObservations()
    for record in records:
        context = _rubric_score_record_context(record)
        _collect_generation_observations(target, record, context, observations)
        _collect_rubric_role_observations(target, record, context, observations)
    return observations


def _summarize_rubric_scores(
    targets: tuple[rh.EvaluationTarget, ...],
    records: list[dict[str, object]],
    models: tuple[str, ...],
) -> list[dict[str, object]]:
    """Summarize the selected and generated-rubric rubric_score panel."""

    by_assignment: dict[str, list[dict[str, object]]] = {}
    for record in records:
        by_assignment.setdefault(str(record["assignment_id"]), []).append(record)
    results: list[dict[str, object]] = []
    for target in targets:
        observations = _collect_rubric_score_observations(
            target,
            by_assignment[target.assignment_id],
        )
        original = {
            artifact: rubric_score._score_panel(
                observations.rubrics,
                "original",
                None,
                artifact,
                models,
            )
            for artifact in rh.ARTIFACTS
        }
        active_local = {
            artifact: rubric_score._generation_score_panel(
                target,
                artifact,
                "active_local",
                observations.generations,
                models,
            )
            for artifact in rh.ARTIFACTS
        }
        selected = {
            artifact: rubric_score._score_panel(
                observations.rubrics,
                "selected",
                target.selection.optimizer_index,
                artifact,
                models,
            )
            for artifact in rh.ARTIFACTS
        }
        components = {
            artifact: {
                "verifier_exploitation": (
                    target.weak_original_score(artifact)
                    - float(original[artifact]["mean"])
                ),
            }
            for artifact in rh.ARTIFACTS
        }
        diagnostics = {
            artifact: {
                "active_to_original": (
                    float(active_local[artifact]["mean"])
                    - float(original[artifact]["mean"])
                ),
                "original_to_selected": (
                    float(original[artifact]["mean"])
                    - float(selected[artifact]["mean"])
                ),
            }
            for artifact in rh.ARTIFACTS
        }
        results.append({
            "assignment_id": target.assignment_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "condition_id": target.condition_id,
            "rubric_policy": target.rubric_policy.value,
            "weak_original_rubric_scores": {
                artifact: target.weak_original_score(artifact)
                for artifact in rh.ARTIFACTS
            },
            "active_local_scores": {
                artifact: {
                    "weak_score": target.weak_active_score(artifact),
                    "strong_score": float(active_local[artifact]["mean"]),
                    "verifier_gap": (
                        target.weak_active_score(artifact)
                        - float(active_local[artifact]["mean"])
                    ),
                    "interpretation": "initial/final score under the active rubric",
                }
                for artifact in rh.ARTIFACTS
            },
            "reference_scores": {
                "original": original,
                "active_local": active_local,
                "selected": selected,
            },
            "score_gap_components": components,
            "rubric_diagnostics": diagnostics,
        })
    return results


class RubricScoreRunner(rubric_score.RubricScoreStage):
    """Score with strong judges that complete every rubric_score job."""

    def run(self) -> int:
        self.preflight()
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("RH rubric score preflight did not produce a plan")
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        manifest = self._manifest(prepared, models)
        self.output.prepare(manifest, self.config.resume)
        unique_jobs = prepared.unique_jobs
        failures = _prior_failures(
            self.output,
            expected_kind=rh.RUBRIC_SCORE_KIND,
        )
        jobs_by_key = {job.key: job for job in unique_jobs}
        if not set(failures) <= set(jobs_by_key):
            raise RuntimeError("RH rubric score failure is outside the accepted plan")
        judgments: dict[str, dict[str, object]] = {}
        fresh_jobs = tuple(
            job for job in unique_jobs if job.key not in failures
        )
        fatal_errors: list[BaseException] = []
        with TerminalProgress(
            total=len(fresh_jobs),
            description="RH rubric score evaluation",
            unit="judgment",
        ) as progress:
            with ThreadPoolExecutor(
                max_workers=self.config.max_concurrency
            ) as pool:
                futures = {
                    pool.submit(self._run_job, job): job
                    for job in fresh_jobs
                }
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        judgments[job.key] = future.result()
                    except Exception as error:
                        if (
                            job.model in models
                            and _is_judge_failure(
                                error,
                                "RH audit rubric judge failed after ",
                            )
                        ):
                            failures[job.key] = _failure_record(
                                key=job.key,
                                model=job.model,
                                error=error,
                            )
                        else:
                            fatal_errors.append(error)
                    progress.update()
        if fatal_errors:
            raise RuntimeError("RH rubric score non-panel job failed") from fatal_errors[0]

        available_models = tuple(
            model
            for model in models
            if all(
                job.key in judgments
                for job in unique_jobs
                if job.model == model
            )
        )
        if not available_models:
            raise RuntimeError("all configured RH rubric score judges failed")
        included_models = set(available_models)
        records = [
            {
                **rubric_score._rubric_score_job_identity(job),
                "judgment_key": job.key,
                "score": judgments[job.key]["score"],
                "attempt_id": judgments[job.key]["attempt_id"],
                "validation_path": judgments[job.key]["validation_path"],
                "evaluation_path": judgments[job.key]["evaluation_path"],
            }
            for job in prepared.jobs
            if job.model in included_models
        ]
        records.sort(key=rh._record_sort_key)
        failure_records = sorted(
            failures.values(),
            key=lambda item: (str(item["model"]), str(item["judgment_key"])),
        )
        summary = {
            **manifest,
            "status": "completed",
            "panel_policy": PANEL_POLICY,
            "available_models": list(available_models),
            "failed_models": [
                model for model in models if model not in available_models
            ],
            "rubric_scope": "original-active-selected",
            "planned_semantic_judgment_count": len(unique_jobs),
            "successful_semantic_judgment_count": len(judgments),
            "used_semantic_judgment_count": len({
                job.key
                for job in unique_jobs
                if job.model in included_models
            }),
            "failed_semantic_judgment_count": len(failure_records),
            "assignment_reference_count": len(records),
            "judge_failures": failure_records,
            "records": records,
            "assignments": _summarize_rubric_scores(
                prepared.targets,
                records,
                available_models,
            ),
        }
        self._write_summary(summary)
        return 0

    def _write_summary(self, summary: dict[str, object]) -> None:
        self.output.write_json(("summary.json",), summary)

    def _manifest(
        self,
        prepared: rh.PreparedRubricScoreEvaluation,
        models: tuple[str, ...],
    ) -> dict[str, object]:
        jobs = prepared.jobs
        study_experiment_id = _study_experiment_id(prepared.targets)
        return {
            "kind": rh.RUBRIC_SCORE_KIND,
            "experiment_id": self.config.experiment.experiment_id,
            "study_experiment_id": study_experiment_id,
            "study_dir": str(self.config.study_dir.resolve()),
            "paraphrase_dir": str(self.config.paraphrase_dir.resolve()),
            "models": list(models),
            "model_routes": {
                model: rh._model_route(self.config.vllm_endpoints.get(model))
                for model in sorted({job.model for job in jobs})
            },
            "implementation_identity": rh._rubric_score_implementation_identity(
                prepared.unique_jobs
            ),
            "assignment_reference_count": len(jobs),
            "assignment_reference_identity_sha256": (
                rubric_score._rubric_score_assignment_reference_sha256(jobs)
            ),
            "artifacts": list(rh.ARTIFACTS),
            "endpoint_rubric": "original-master-rubric",
            "semantic_deduplication": (
                "benchmark-task-content-rubric-model-route-engine-"
                "implementation-repeat; original, active, and selected roles "
                "do not duplicate an exact "
                "semantic request"
            ),
            "loss_weights": self.config.experiment.outcome_audit["loss_weights"],
            "predispatch_plan": prepared.predispatch_plan,
        }


class RubricFreeEvaluationRunner(rubric_free_evaluation.RubricFreeEvaluationStage):
    """Score with strong judges that complete every rubric-free job."""

    def run(self) -> int:
        self.preflight()
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("RH rubric-free evaluation preflight did not produce a plan")
        manifest = self._manifest(prepared)
        self.output.prepare(manifest, self.config.resume)
        failures = _prior_failures(
            self.output,
            expected_kind=rh.RUBRIC_FREE_EVALUATION_KIND,
            instruments=frozenset({"absolute", "pairwise"}),
        )
        unique_absolute = {
            job.key: job for job in prepared.unique_absolute_jobs
        }
        unique_pairwise = {
            job.key: job for job in prepared.unique_pairwise_jobs
        }
        all_keys = set(unique_absolute) | set(unique_pairwise)
        if not set(failures) <= all_keys:
            raise RuntimeError("RH rubric-free evaluation failure is outside the accepted plan")
        absolute_judgments: dict[str, dict[str, object]] = {}
        pairwise_judgments: dict[str, dict[str, object]] = {}
        jobs = [
            ("absolute", job)
            for job in prepared.unique_absolute_jobs
            if job.key not in failures
        ] + [
            ("pairwise", job)
            for job in prepared.unique_pairwise_jobs
            if job.key not in failures
        ]
        fatal_errors: list[BaseException] = []
        with TerminalProgress(
            total=len(jobs),
            description="RH rubric-free outcome evaluation",
            unit="judgment",
        ) as progress:
            with ThreadPoolExecutor(
                max_workers=self.config.max_concurrency
            ) as pool:
                futures = {
                    pool.submit(
                        self._run_absolute_job
                        if instrument == "absolute"
                        else self._run_pairwise_job,
                        job,
                    ): (instrument, job)
                    for instrument, job in jobs
                }
                for future in as_completed(futures):
                    instrument, job = futures[future]
                    try:
                        judgment = future.result()
                        if instrument == "absolute":
                            absolute_judgments[job.key] = judgment
                        else:
                            pairwise_judgments[job.key] = judgment
                    except Exception as error:
                        if _is_judge_failure(
                            error,
                            "RH rubric-free judge failed after ",
                        ):
                            failures[job.key] = _failure_record(
                                key=job.key,
                                model=job.model,
                                instrument=instrument,
                                error=error,
                            )
                        else:
                            fatal_errors.append(error)
                    progress.update()
        if fatal_errors:
            raise RuntimeError("RH rubric-free evaluation non-panel job failed") from fatal_errors[0]

        available_models = tuple(
            model
            for model in prepared.models
            if all(
                job.key in absolute_judgments
                for job in prepared.unique_absolute_jobs
                if job.model == model
            )
            and all(
                job.key in pairwise_judgments
                for job in prepared.unique_pairwise_jobs
                if job.model == model
            )
        )
        if not available_models:
            raise RuntimeError("all configured RH rubric-free judges failed")
        available_set = set(available_models)
        absolute_records = [
            rubric_free_evaluation._absolute_assignment_reference(
                job,
                absolute_judgments[job.key],
            )
            for job in prepared.absolute_jobs
            if job.model in available_set
        ]
        pairwise_records = [
            rubric_free_evaluation._pairwise_assignment_reference(
                job,
                pairwise_judgments[job.key],
            )
            for job in prepared.pairwise_jobs
            if job.model in available_set
        ]
        absolute_records.sort(key=rh._record_sort_key)
        pairwise_records.sort(key=rh._record_sort_key)
        failure_records = sorted(
            failures.values(),
            key=lambda item: (
                str(item["instrument"]),
                str(item["model"]),
                str(item["judgment_key"]),
            ),
        )
        used_absolute = {
            key for key, job in unique_absolute.items() if job.model in available_set
        }
        used_pairwise = {
            key for key, job in unique_pairwise.items() if job.model in available_set
        }
        summary = {
            **manifest,
            "status": "completed",
            "panel_policy": PANEL_POLICY,
            "available_models": list(available_models),
            "failed_models": [
                model for model in prepared.models if model not in available_set
            ],
            "planned_semantic_judgment_counts": {
                "absolute": len(unique_absolute),
                "pairwise": len(unique_pairwise),
            },
            "successful_semantic_judgment_counts": {
                "absolute": len(absolute_judgments),
                "pairwise": len(pairwise_judgments),
            },
            "used_semantic_judgment_counts": {
                "absolute": len(used_absolute),
                "pairwise": len(used_pairwise),
            },
            "failed_semantic_judgment_count": len(failure_records),
            "assignment_reference_counts": {
                "absolute": len(absolute_records),
                "pairwise": len(pairwise_records),
            },
            "judge_failures": failure_records,
            "absolute_records": absolute_records,
            "pairwise_records": pairwise_records,
            "completed_record_sha256s": {
                "absolute": {
                    key: sha256_file(self.output.regular_file(
                        "records", "absolute", f"{key}.json"
                    ))
                    for key in sorted(used_absolute)
                },
                "pairwise": {
                    key: sha256_file(self.output.regular_file(
                        "records", "pairwise", f"{key}.json"
                    ))
                    for key in sorted(used_pairwise)
                },
            },
            "assignments": rubric_free_evaluation._summarize_rubric_free_scores(
                prepared.targets,
                absolute_records,
                pairwise_records,
                available_models,
            ),
        }
        self._write_summary(summary)
        return 0

    def _write_summary(self, summary: dict[str, object]) -> None:
        self.output.write_json(("summary.json",), summary)

    def _manifest(
        self,
        prepared: rh.PreparedRubricFreeEvaluation,
    ) -> dict[str, object]:
        return {
            "kind": rh.RUBRIC_FREE_EVALUATION_KIND,
            "experiment_id": self.config.experiment.experiment_id,
            "study_experiment_id": _study_experiment_id(prepared.targets),
            "study_dir": str(self.config.study_dir.resolve()),
            "models": list(prepared.models),
            "model_routes": {
                model: rh._model_route(self.config.vllm_endpoints.get(model))
                for model in prepared.models
            },
            "implementation_identity": prepared.implementation_identity,
            "orderings": list(rh.ORDERINGS),
            "absolute_prompt_id": rh.ABSOLUTE_PROMPT_ID,
            "pairwise_prompt_id": rh.PAIRWISE_PROMPT_ID,
            "semantic_deduplication": (
                "benchmark-task-content-rubric-model-route-engine-"
                "implementation-repeat-or-order"
            ),
            "predispatch_plan": prepared.predispatch_plan,
        }


def _study_experiment_id(
    targets: tuple[rh.EvaluationTarget, ...],
) -> str:
    values = {target.study_experiment_id for target in targets}
    if len(values) != 1:
        raise RuntimeError("RH targets must use one source study experiment ID")
    return next(iter(values))
