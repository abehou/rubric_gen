"""Run RH outcome scoring with every stage-complete strong judge."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision import rh_protocol as rh
from rubric_gen.submission_revision import rh_holistic as holistic
from rubric_gen.submission_revision import rh_mechanistic as mechanistic
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.rh_output_store import RhOutputStore


PANEL_POLICY: dict[str, object] = {
    "aggregation": "arithmetic-mean-over-stage-complete-judges",
    "minimum_stage_complete_judges": 1,
    "configured_judge_failure_scope": "whole-stage",
    "weak_rescore_failure": "terminal",
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
class _MechanisticObservations:
    selected: dict[tuple[str, int | None, str, str], float] = field(
        default_factory=dict
    )
    bank: dict[tuple[str, str, str, str], float] = field(default_factory=dict)
    anchors: dict[tuple[str, str, str, str], float] = field(default_factory=dict)


def _store_unique(
    observations: dict[tuple[object, ...], float],
    key: tuple[object, ...],
    score: float,
    label: str,
) -> None:
    if key in observations:
        raise RuntimeError(f"duplicate RH {label} observation: {key}")
    observations[key] = score


def _mechanistic_record_context(
    record: dict[str, object],
) -> tuple[str, str, float, str]:
    boundary = str(record["boundary"])
    model = str(record["model"])
    score = rh._finite_score(record.get("score"), "RH mechanistic score")
    rubric_sha256 = record.get("rubric_sha256")
    if not rh._is_sha256(rubric_sha256):
        raise RuntimeError("RH mechanistic record has an invalid rubric hash")
    return boundary, model, score, str(rubric_sha256)


def _collect_bank_observations(
    target: rh.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _MechanisticObservations,
) -> None:
    boundary, model, score, rubric_sha256 = context
    bindings = record.get("bank_members")
    if not isinstance(bindings, list):
        raise RuntimeError("RH bank-member bindings are invalid")
    for binding in bindings:
        if not isinstance(binding, dict):
            raise RuntimeError("RH bank-member binding is invalid")
        bank_role = binding.get("bank_role")
        if bank_role == "terminal_common":
            generation = target.final_bank_generation
        elif bank_role == "online_local":
            generation = target.bank_generation(boundary)
        else:
            raise RuntimeError("RH bank-member binding has an invalid role")
        items = {
            item.rubric.content_sha256: item for item in generation.bank.items
        }
        member_hash = binding.get("member_sha256")
        if type(member_hash) is not str or member_hash not in items:
            raise RuntimeError("RH bank-member binding is outside the bank")
        if member_hash != rubric_sha256:
            raise RuntimeError(
                "RH bank-member binding does not match the judged rubric"
            )
        expected = mechanistic._expected_bank_binding(
            target,
            boundary,
            items[member_hash],
            str(bank_role),
        ).payload()
        if binding != expected:
            raise RuntimeError("RH bank-member binding changed")
        _store_unique(
            observations.bank,
            (str(bank_role), boundary, model, member_hash),
            score,
            "bank-member",
        )


def _collect_anchor_observations(
    target: rh.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _MechanisticObservations,
) -> None:
    boundary, model, score, rubric_sha256 = context
    anchors = record.get("specification_anchors")
    if not isinstance(anchors, list):
        raise RuntimeError("RH specification-anchor bindings are invalid")
    expected = mechanistic._expected_specification_anchor_binding(target).payload()
    expected_hash = target.final_bank_generation.bank.specification_anchor.content_sha256
    for anchor in anchors:
        if (
            not isinstance(anchor, dict)
            or anchor != expected
            or anchor.get("specification_anchor_sha256") != expected_hash
            or expected_hash != rubric_sha256
        ):
            raise RuntimeError("RH specification-anchor binding changed")
        _store_unique(
            observations.anchors,
            ("terminal_common", boundary, model, expected_hash),
            score,
            "specification-anchor",
        )


def _collect_selected_observations(
    target: rh.EvaluationTarget,
    record: dict[str, object],
    context: tuple[str, str, float, str],
    observations: _MechanisticObservations,
) -> None:
    boundary, model, score, rubric_sha256 = context
    roles = record.get("rubric_roles")
    if not isinstance(roles, list):
        raise RuntimeError("RH mechanistic record has no rubric roles")
    expected = {
        "name": "selected",
        "variant_index": target.selection.optimizer_index,
    }
    for role in roles:
        if role != expected or rubric_sha256 != target.selection.optimizer_sha256:
            raise RuntimeError(
                "RH mechanistic rubric role does not match the judged rubric"
            )
        _store_unique(
            observations.selected,
            ("selected", target.selection.optimizer_index, boundary, model),
            score,
            "mechanistic",
        )


def _collect_mechanistic_observations(
    target: rh.EvaluationTarget,
    records: list[dict[str, object]],
) -> _MechanisticObservations:
    observations = _MechanisticObservations()
    for record in records:
        context = _mechanistic_record_context(record)
        _collect_bank_observations(target, record, context, observations)
        _collect_anchor_observations(target, record, context, observations)
        _collect_selected_observations(target, record, context, observations)
    return observations


def _summarize_mechanistic_scores(
    targets: tuple[rh.EvaluationTarget, ...],
    records: list[dict[str, object]],
    models: tuple[str, ...],
) -> list[dict[str, object]]:
    """Summarize the selected and bank-based mechanistic panel."""

    by_assignment: dict[str, list[dict[str, object]]] = {}
    for record in records:
        by_assignment.setdefault(str(record["assignment_id"]), []).append(record)
    results: list[dict[str, object]] = []
    for target in targets:
        observations = _collect_mechanistic_observations(
            target,
            by_assignment[target.assignment_id],
        )
        terminal_common = {
            boundary: mechanistic._bank_score_panel(
                target,
                boundary,
                "terminal_common",
                observations.bank,
                models,
            )
            for boundary in rh.BOUNDARIES
        }
        terminal_weak = {
            boundary: mechanistic._bank_score_panel(
                target,
                boundary,
                "terminal_common",
                observations.bank,
                (target.weak_model,),
            )
            for boundary in rh.BOUNDARIES
        }
        online_local = {
            boundary: mechanistic._bank_score_panel(
                target,
                boundary,
                "online_local",
                observations.bank,
                models,
            )
            for boundary in rh.BOUNDARIES
        }
        terminal_anchor = {
            boundary: mechanistic._specification_anchor_score_panel(
                target,
                boundary,
                observations.anchors,
                models,
            )
            for boundary in rh.BOUNDARIES
        }
        selected = {
            boundary: mechanistic._score_panel(
                observations.selected,
                "selected",
                target.selection.optimizer_index,
                boundary,
                models,
            )
            for boundary in rh.BOUNDARIES
        }
        components = {
            boundary: {
                "verifier_exploitation": (
                    float(terminal_weak[boundary]["mean"])
                    - float(terminal_common[boundary]["mean"])
                ),
            }
            for boundary in rh.BOUNDARIES
        }
        diagnostics = {
            boundary: {
                "active_to_original": (
                    float(terminal_common[boundary]["mean"])
                    - float(terminal_anchor[boundary]["mean"])
                ),
                "original_to_selected": (
                    float(terminal_anchor[boundary]["mean"])
                    - float(selected[boundary]["mean"])
                ),
            }
            for boundary in rh.BOUNDARIES
        }
        results.append({
            "assignment_id": target.assignment_id,
            "task_id": target.task_id,
            "replicate": target.replicate,
            "condition_id": target.condition_id,
            "rubric_policy": target.rubric_policy.value,
            "weak_terminal_bank_scores": {
                boundary: float(terminal_weak[boundary]["mean"])
                for boundary in rh.BOUNDARIES
            },
            "online_local_scores": {
                boundary: {
                    "weak_score": target.weak_score(boundary),
                    "strong_score": float(online_local[boundary]["mean"]),
                    "verifier_gap": (
                        target.weak_score(boundary)
                        - float(online_local[boundary]["mean"])
                    ),
                    "interpretation": "ruler-confounded boundary-local score",
                }
                for boundary in rh.BOUNDARIES
            },
            "reference_scores": {
                "terminal_common": terminal_common,
                "terminal_weak": terminal_weak,
                "online_local": online_local,
                "terminal_specification_anchor": terminal_anchor,
                "selected": selected,
            },
            "mechanistic_components": components,
            "rubric_diagnostics": diagnostics,
        })
    return results


class MechanisticEvaluationRunner(mechanistic.MechanisticEvaluationStage):
    """Score with strong judges that complete every mechanistic job."""

    def run(self) -> int:
        self.preflight()
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("RH mechanistic preflight did not produce a plan")
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        weak_model = str(self.config.experiment.protocol["judge_model"])
        manifest = self._manifest(prepared, models, weak_model)
        self.output.prepare(manifest, self.config.resume)
        unique_jobs = prepared.unique_jobs
        failures = _prior_failures(
            self.output,
            expected_kind=rh.MECHANISTIC_KIND,
        )
        jobs_by_key = {job.key: job for job in unique_jobs}
        if not set(failures) <= set(jobs_by_key):
            raise RuntimeError("RH mechanistic failure is outside the accepted plan")
        judgments: dict[str, dict[str, object]] = {}
        fresh_jobs = tuple(
            job for job in unique_jobs if job.key not in failures
        )
        fatal_errors: list[BaseException] = []
        with TerminalProgress(
            total=len(fresh_jobs),
            description="RH mechanistic evaluation",
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
                            and job.model != weak_model
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
            raise RuntimeError("RH mechanistic non-panel job failed") from fatal_errors[0]

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
            raise RuntimeError("all configured RH mechanistic judges failed")
        weak_jobs = tuple(
            job for job in unique_jobs if job.model == weak_model
        )
        if any(job.key not in judgments for job in weak_jobs):
            raise RuntimeError("RH mechanistic weak rescore judge failed")

        included_models = set(available_models) | {weak_model}
        records = [
            {
                **mechanistic._mechanistic_job_identity(job),
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
            "rubric_scope": "terminal-local-anchor-selected",
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
            "assignments": _summarize_mechanistic_scores(
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
        prepared: rh.PreparedMechanisticEvaluation,
        models: tuple[str, ...],
        weak_model: str,
    ) -> dict[str, object]:
        jobs = prepared.jobs
        return {
            "kind": rh.MECHANISTIC_KIND,
            "experiment_id": self.config.experiment.experiment_id,
            "study_dir": str(self.config.study_dir.resolve()),
            "paraphrase_dir": str(self.config.paraphrase_dir.resolve()),
            "models": list(models),
            "weak_rescore_model": weak_model,
            "model_routes": {
                model: rh._model_route(self.config.vllm_endpoints.get(model))
                for model in sorted({job.model for job in jobs})
            },
            "implementation_identity": rh._mechanistic_implementation_identity(
                prepared.unique_jobs
            ),
            "assignment_reference_count": len(jobs),
            "assignment_reference_identity_sha256": (
                mechanistic._mechanistic_assignment_reference_sha256(jobs)
            ),
            "boundaries": list(rh.BOUNDARIES),
            "endpoint_bank": "frozen-terminal-bank",
            "semantic_deduplication": (
                "benchmark-task-content-rubric-model-route-engine-"
                "implementation-repeat; terminal specification-anchor, bank-"
                "member, and selected roles do not duplicate an exact "
                "semantic request"
            ),
            "loss_weights": self.config.experiment.outcome_audit["loss_weights"],
            "predispatch_plan": prepared.predispatch_plan,
        }


class HolisticPairwiseRunner(holistic.HolisticEvaluationStage):
    """Score with strong judges that complete every rubric-free job."""

    def run(self) -> int:
        self.preflight()
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("RH holistic preflight did not produce a plan")
        manifest = self._manifest(prepared)
        self.output.prepare(manifest, self.config.resume)
        failures = _prior_failures(
            self.output,
            expected_kind=rh.HOLISTIC_KIND,
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
            raise RuntimeError("RH holistic failure is outside the accepted plan")
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
                            "RH holistic judge failed after ",
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
            raise RuntimeError("RH holistic non-panel job failed") from fatal_errors[0]

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
            raise RuntimeError("all configured RH holistic judges failed")
        available_set = set(available_models)
        absolute_records = [
            holistic._absolute_assignment_reference(
                job,
                absolute_judgments[job.key],
            )
            for job in prepared.absolute_jobs
            if job.model in available_set
        ]
        pairwise_records = [
            holistic._pairwise_assignment_reference(
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
            "assignments": holistic._summarize_holistic_scores(
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
        prepared: rh.PreparedHolisticEvaluation,
    ) -> dict[str, object]:
        return {
            "kind": rh.HOLISTIC_KIND,
            "experiment_id": self.config.experiment.experiment_id,
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
