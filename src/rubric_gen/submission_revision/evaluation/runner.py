"""Run evaluation outcome scoring with every stage-complete strong judge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.evaluation import (
    absolute_score,
    pairwise_preference,
    jobs as evaluation_jobs,
    rubric_score,
    score_execution,
)
from rubric_gen.submission_revision.evaluation.store import EvaluationStore


PANEL_POLICY: dict[str, object] = {
    "aggregation": "arithmetic-mean-over-complete-configured-panel",
    "configured_judge_failure_scope": "incomplete-stage",
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
        raise RuntimeError(f"duplicate evaluation {label} observation: {key}")
    observations[key] = score


def _rubric_score_record_context(
    record: dict[str, object],
) -> tuple[str, str, float, str]:
    artifact = str(record["artifact"])
    model = str(record["model"])
    score = evaluation_jobs._finite_score(record.get("score"), "revision rubric score score")
    rubric_sha256 = record.get("rubric_sha256")
    if not evaluation_jobs._is_sha256(rubric_sha256):
        raise RuntimeError("revision rubric score record has an invalid rubric hash")
    return artifact, model, score, str(rubric_sha256)


def _collect_generation_observations(
    target: evaluation_jobs.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _RubricScoreObservations,
) -> None:
    artifact, model, score, rubric_sha256 = context
    bindings = record.get("generation_bindings")
    if not isinstance(bindings, list):
        raise RuntimeError("evaluation generation bindings are invalid")
    for binding in bindings:
        if not isinstance(binding, dict):
            raise RuntimeError("evaluation generation binding is invalid")
        role = binding.get("role")
        if role == "active_local":
            generation = target.generation(artifact)
        else:
            raise RuntimeError("evaluation generation binding has an invalid role")
        if generation.rubric.content_sha256 != rubric_sha256:
            raise RuntimeError("evaluation generation binding has the wrong rubric")
        expected = rubric_score._expected_generation_binding(
            target,
            artifact,
            str(role),
        ).payload()
        if binding != expected:
            raise RuntimeError("evaluation generation binding changed")
        _store_unique(
            observations.generations,
            (str(role), artifact, model, rubric_sha256),
            score,
            "generation",
        )


def _collect_rubric_role_observations(
    target: evaluation_jobs.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _RubricScoreObservations,
) -> None:
    artifact, model, score, rubric_sha256 = context
    roles = record.get("rubric_roles")
    if not isinstance(roles, list):
        raise RuntimeError("revision rubric score record has no rubric roles")
    for role in roles:
        if role == {"name": "original", "variant_index": None}:
            expected_sha256 = target.selection.master_sha256
        elif role == {
            "name": "selected",
            "variant_index": target.selection.optimizer_index,
        }:
            expected_sha256 = target.selection.optimizer_sha256
        elif (
            role.get("name") == "holdout"
            and type(role.get("variant_index")) is int
        ):
            holdout_by_index = {
                int(path.stem.removeprefix("variant-")): digest
                for path, digest in zip(
                    target.selection.holdout_paths,
                    target.selection.holdout_sha256s,
                    strict=True,
                )
            }
            expected_sha256 = holdout_by_index.get(role["variant_index"])
            if expected_sha256 is None:
                raise RuntimeError(
                    "revision rubric score rubric role does not match the judged rubric"
                )
        else:
            raise RuntimeError(
                "revision rubric score rubric role does not match the judged rubric"
            )
        if rubric_sha256 != expected_sha256:
            raise RuntimeError(
                "revision rubric score rubric role does not match the judged rubric"
            )
        _store_unique(
            observations.rubrics,
            (str(role["name"]), role["variant_index"], artifact, model),
            score,
            "rubric_score",
        )


def _collect_rubric_score_observations(
    target: evaluation_jobs.EvaluationTarget,
    records: list[dict[str, object]],
) -> _RubricScoreObservations:
    observations = _RubricScoreObservations()
    for record in records:
        context = _rubric_score_record_context(record)
        _collect_generation_observations(target, record, context, observations)
        _collect_rubric_role_observations(target, record, context, observations)
    return observations


def _summarize_rubric_scores(
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
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
            for artifact in evaluation_jobs.ARTIFACTS
        }
        active_local = {
            artifact: rubric_score._generation_score_panel(
                target,
                artifact,
                "active_local",
                observations.generations,
                models,
            )
            for artifact in evaluation_jobs.ARTIFACTS
        }
        selected = {
            artifact: rubric_score._score_panel(
                observations.rubrics,
                "selected",
                target.selection.optimizer_index,
                artifact,
                models,
            )
            for artifact in evaluation_jobs.ARTIFACTS
        }
        holdout = {
            artifact: rubric_score._holdout_score_panel(
                observations.rubrics,
                target,
                artifact,
                models,
            )
            for artifact in evaluation_jobs.ARTIFACTS
        }
        components = {
            artifact: {
                "verifier_exploitation": (
                    target.weak_original_score(artifact)
                    - float(original[artifact]["mean"])
                ),
            }
            for artifact in evaluation_jobs.ARTIFACTS
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
            for artifact in evaluation_jobs.ARTIFACTS
        }
        results.append({
            "assignment_id": target.assignment_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "solver_id": target.solver_id,
            "condition_id": target.condition_id,
            "rubric_policy": target.rubric_policy.value,
            "weak_original_rubric_scores": {
                artifact: target.weak_original_score(artifact)
                for artifact in evaluation_jobs.ARTIFACTS
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
                for artifact in evaluation_jobs.ARTIFACTS
            },
            "reference_scores": {
                "original": original,
                "active_local": active_local,
                "selected": selected,
                "holdout": holdout,
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
            raise RuntimeError("revision rubric score preflight did not produce a plan")
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        manifest = self._manifest(prepared, models)
        self.output.prepare(manifest, self.config.resume)
        unique_jobs = prepared.unique_jobs
        failures: dict[str, dict[str, object]] = {}
        judgments: dict[str, dict[str, object]] = {}
        fatal_errors: list[BaseException] = []
        with TerminalProgress(
            total=len(unique_jobs),
            description="revision rubric score evaluation",
            unit="judgment",
        ) as progress:
            with ThreadPoolExecutor(
                max_workers=self.config.max_concurrency
            ) as pool:
                futures = {
                    pool.submit(self._run_job, job): job
                    for job in unique_jobs
                }
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        judgments[job.key] = future.result()
                        failures.pop(job.key, None)
                    except Exception as error:
                        if (
                            job.model in models
                            and _is_judge_failure(
                                error,
                                "rubric-score rubric judge failed after ",
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
            raise RuntimeError("revision rubric score non-panel job failed") from fatal_errors[0]

        missing_models = tuple(
            model
            for model in models
            if any(
                job.key not in judgments
                for job in unique_jobs
                if job.model == model
            )
        )
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
            if job.key in judgments
        ]
        records.sort(key=evaluation_jobs._record_sort_key)
        failure_records = sorted(
            failures.values(),
            key=lambda item: (str(item["model"]), str(item["judgment_key"])),
        )
        summary = {
            **manifest,
            "status": "incomplete" if missing_models else "completed",
            "panel_policy": PANEL_POLICY,
            "missing_models": list(missing_models),
            "rubric_scope": "original-active-selected-holdout",
            "planned_semantic_judgment_count": len(unique_jobs),
            "successful_semantic_judgment_count": len(judgments),
            "used_semantic_judgment_count": len(judgments),
            "failed_semantic_judgment_count": len(failure_records),
            "assignment_reference_count": len(records),
            "judge_failures": failure_records,
            "records": records,
            "assignments": (
                []
                if missing_models
                else _summarize_rubric_scores(
                    prepared.targets,
                    records,
                    models,
                )
            ),
        }
        self._write_summary(summary)
        return 1 if missing_models else 0

    def _write_summary(self, summary: dict[str, object]) -> None:
        self.output.write_json(("summary.json",), summary)

    def _manifest(
        self,
        prepared: evaluation_jobs.PreparedRubricScoreEvaluation,
        models: tuple[str, ...],
    ) -> dict[str, object]:
        jobs = prepared.jobs
        study_experiment_id = _study_experiment_id(prepared.targets)
        return {
            "kind": evaluation_jobs.RUBRIC_SCORE_KIND,
            "experiment_id": self.config.experiment.experiment_id,
            "study_experiment_id": study_experiment_id,
            "study_dir": str(self.config.study_dir.resolve()),
            "assignment_coverage": _assignment_coverage(
                self.config,
                prepared.targets,
            ),
            "paraphrase_dir": str(self.config.paraphrase_dir.resolve()),
            "models": list(models),
            "implementation_identity": evaluation_jobs._rubric_score_implementation_identity(
                prepared.unique_jobs
            ),
            "assignment_reference_count": len(jobs),
            "assignment_reference_identity_sha256": (
                rubric_score._rubric_score_assignment_reference_sha256(jobs)
            ),
            "artifacts": list(evaluation_jobs.ARTIFACTS),
            "endpoint_rubric": "original-master-rubric",
            "semantic_deduplication": (
                "benchmark-task-content-rubric-model-engine-"
                "implementation; original, active, selected, and holdout roles "
                "do not duplicate an exact "
                "semantic request"
            ),
            "loss_weights": self.config.experiment.outcome_audit["loss_weights"],
            "predispatch_plan": prepared.predispatch_plan,
        }


class RubricFreeScoreRunner(score_execution.RubricFreeScoreStage):
    """Run the absolute-score and pairwise-preference instruments."""

    def run(self) -> int:
        self.preflight()
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("rubric-free score preflight did not produce a plan")
        manifests = self._manifests(prepared)
        self.absolute_output.prepare(manifests["absolute"], self.config.resume)
        self.pairwise_output.prepare(manifests["pairwise"], self.config.resume)
        absolute_failures: dict[str, dict[str, object]] = {}
        pairwise_failures: dict[str, dict[str, object]] = {}
        unique_absolute = {
            job.key: job for job in prepared.unique_absolute_jobs
        }
        unique_pairwise = {
            job.key: job for job in prepared.unique_pairwise_jobs
        }
        absolute_judgments: dict[str, dict[str, object]] = {}
        pairwise_judgments: dict[str, dict[str, object]] = {}
        jobs = [
            ("absolute", job)
            for job in prepared.unique_absolute_jobs
        ] + [
            ("pairwise", job)
            for job in prepared.unique_pairwise_jobs
        ]
        fatal_errors: list[BaseException] = []
        with TerminalProgress(
            total=len(jobs),
            description="absolute and pairwise scoring",
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
                            absolute_failures.pop(job.key, None)
                        else:
                            pairwise_judgments[job.key] = judgment
                            pairwise_failures.pop(job.key, None)
                    except Exception as error:
                        if _is_judge_failure(
                            error,
                            "rubric-free score judge failed after ",
                        ):
                            failure = _failure_record(
                                key=job.key,
                                model=job.model,
                                instrument=instrument,
                                error=error,
                            )
                            if instrument == "absolute":
                                absolute_failures[job.key] = failure
                            else:
                                pairwise_failures[job.key] = failure
                        else:
                            fatal_errors.append(error)
                    progress.update()
        if fatal_errors:
            raise RuntimeError("rubric-free score job failed") from fatal_errors[0]

        missing_models = tuple(
            model
            for model in prepared.models
            if any(
                job.key not in absolute_judgments
                for job in prepared.unique_absolute_jobs
                if job.model == model
            )
            or any(
                job.key not in pairwise_judgments
                for job in prepared.unique_pairwise_jobs
                if job.model == model
            )
        )
        absolute_records = [
            absolute_score.assignment_reference(
                job,
                absolute_judgments[job.key],
            )
            for job in prepared.absolute_jobs
            if job.key in absolute_judgments
        ]
        pairwise_records = [
            pairwise_preference.assignment_reference(
                job,
                pairwise_judgments[job.key],
            )
            for job in prepared.pairwise_jobs
            if job.key in pairwise_judgments
        ]
        absolute_records.sort(key=evaluation_jobs._record_sort_key)
        pairwise_records.sort(key=evaluation_jobs._record_sort_key)
        absolute_failure_records = sorted(
            absolute_failures.values(),
            key=lambda item: (
                str(item["model"]),
                str(item["judgment_key"]),
            ),
        )
        pairwise_failure_records = sorted(
            pairwise_failures.values(),
            key=lambda item: (
                str(item["model"]),
                str(item["judgment_key"]),
            ),
        )
        used_absolute = set(absolute_judgments)
        used_pairwise = set(pairwise_judgments)
        common = {
            "status": "incomplete" if missing_models else "completed",
            "panel_policy": PANEL_POLICY,
            "missing_models": list(missing_models),
        }
        absolute_summary = {
            **manifests["absolute"],
            **common,
            "planned_semantic_judgment_count": len(unique_absolute),
            "successful_semantic_judgment_count": len(absolute_judgments),
            "used_semantic_judgment_count": len(used_absolute),
            "failed_semantic_judgment_count": len(absolute_failure_records),
            "assignment_reference_count": len(absolute_records),
            "judge_failures": absolute_failure_records,
            "records": absolute_records,
            "completed_record_sha256s": {
                key: sha256_file(self.absolute_output.regular_file(
                    "records", f"{key}.json"
                ))
                for key in sorted(used_absolute)
            },
            "assignments": (
                []
                if missing_models
                else absolute_score.summarize(
                    prepared.targets,
                    absolute_records,
                    prepared.models,
                )
            ),
        }
        pairwise_summary = {
            **manifests["pairwise"],
            **common,
            "planned_semantic_judgment_count": len(unique_pairwise),
            "successful_semantic_judgment_count": len(pairwise_judgments),
            "used_semantic_judgment_count": len(used_pairwise),
            "failed_semantic_judgment_count": len(pairwise_failure_records),
            "assignment_reference_count": len(pairwise_records),
            "judge_failures": pairwise_failure_records,
            "records": pairwise_records,
            "completed_record_sha256s": {
                key: sha256_file(self.pairwise_output.regular_file(
                    "records", f"{key}.json"
                ))
                for key in sorted(used_pairwise)
            },
            "assignments": (
                []
                if missing_models
                else pairwise_preference.summarize(
                    prepared.targets,
                    pairwise_records,
                    prepared.models,
                    prepared.pairwise_order_plan,
                )
            ),
        }
        self.absolute_output.write_json(("summary.json",), absolute_summary)
        self.pairwise_output.write_json(("summary.json",), pairwise_summary)
        return 1 if missing_models else 0

    def _manifests(
        self,
        prepared: evaluation_jobs.PreparedRubricFreeScores,
    ) -> dict[str, dict[str, object]]:
        common = {
            "experiment_id": self.config.experiment.experiment_id,
            "study_experiment_id": _study_experiment_id(prepared.targets),
            "study_dir": str(self.config.study_dir.resolve()),
            "assignment_coverage": _assignment_coverage(
                self.config,
                prepared.targets,
            ),
            "models": list(prepared.models),
            "implementation_identity": prepared.implementation_identity,
            "semantic_deduplication": (
                "benchmark-task-content-rubric-model-engine-"
                "implementation-or-order"
            ),
            "predispatch_plan": prepared.predispatch_plan,
        }
        return {
            "absolute": {
                **common,
                "kind": evaluation_jobs.ABSOLUTE_SCORE_KIND,
                "artifacts": list(evaluation_jobs.ARTIFACTS),
                "prompt_id": evaluation_jobs.ABSOLUTE_PROMPT_ID,
            },
            "pairwise": {
                **common,
                "kind": evaluation_jobs.PAIRWISE_PREFERENCE_KIND,
                "orders": list(evaluation_jobs.PAIRWISE_ORDERS),
                "order_assignment": "balanced-task-replicate-plan",
                "order_plan": [
                    {
                        "task_id": task_id,
                        "replicate": replicate,
                        "order": order,
                    }
                    for (task_id, replicate), order in sorted(
                        prepared.pairwise_order_plan.items()
                    )
                ],
                "prompt_id": evaluation_jobs.PAIRWISE_PROMPT_ID,
            },
        }


def _study_experiment_id(
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> str:
    values = {target.study_experiment_id for target in targets}
    if len(values) != 1:
        raise RuntimeError("revision evaluation targets must use one source study experiment ID")
    return next(iter(values))


def _assignment_coverage(
    config: evaluation_jobs.EvaluationConfig,
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> dict[str, object]:
    study = read_json_object(
        config.study_dir.resolve() / "study.json",
        "revision evaluation source study",
    )
    records = study.get("records")
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise RuntimeError("revision evaluation source study records are invalid")
    evaluated_ids = {target.assignment_id for target in targets}
    completed_ids = {
        str(record.get("assignment_id"))
        for record in records
        if record.get("status") == "completed"
    }
    if evaluated_ids != completed_ids:
        raise RuntimeError("revision evaluation targets differ from completed assignments")
    excluded = [
        {
            "assignment_id": str(record.get("assignment_id")),
            "status": str(record.get("status")),
            "error_type": record.get("error_type"),
        }
        for record in records
        if record.get("status") != "completed"
    ]
    return {
        "configured_assignment_count": len(records),
        "evaluated_assignment_count": len(evaluated_ids),
        "excluded_assignment_count": len(excluded),
        "excluded_assignments": excluded,
    }
