"""Reconstruct one complete model from native records in a partial panel audit."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean
import sys

from rubric_gen.submission_revision.evaluation import absolute_score
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import (
    _rubric_score_job_identity,
)
from rubric_gen.submission_revision.evaluation.runner import (
    RubricFreeScoreRunner,
    RubricScoreRunner,
)
from rubric_gen.submission_revision.evaluation.targets import (
    load_evaluation_targets,
)
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.source_resolution import (
    resolve_study_sources,
)


WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _numeric_scores(W: float, train: float, S: float, H: float, A: float):
    values = (W, train, S, H, A)
    if not all(
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= 100
        for value in values
    ):
        raise RuntimeError("saved model reconstruction contains invalid score")
    return {
        "W": W,
        "W_train": train,
        "S": S,
        "H": H,
        "A": A,
        "WS": W - S,
        "SH": S - H,
        "HA": H - A,
        "WA": W - A,
        "train_WS": train - S,
        "train_WA": train - A,
    }


def reconstruct_model(
    experiment: Experiment,
    study: Path,
    audit: Path,
    model: str,
    *,
    expected_holdouts: int = 3,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Validate native records and reconstruct rows without panel completion."""

    if model not in experiment.outcome_audit["models"]:
        raise RuntimeError("requested reconstruction model is outside the audit panel")
    if expected_holdouts < 1:
        raise ValueError("expected_holdouts must be positive")
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts/diagnostics"))
    from artifact_locations import recorded_root
    from check_audit_coverage import source_records
    from rubric_gen.submission_revision.evaluation.direct import (
        DirectDetectionConfig,
        prepare_direct_detection,
    )
    from rubric_gen.submission_revision.detection_windows import (
        RevisionDetectionWindow,
    )

    study = study.resolve()
    audit = audit.resolve()
    sources = resolve_study_sources(study, experiment)
    rubric_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study,
        paraphrase_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
        output_dir=audit / "rubric_score",
        max_concurrency=1,
        resume=True,
    )
    free_config = EvaluationConfig(
        experiment=experiment,
        study_dir=study,
        paraphrase_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
        output_dir=audit,
        max_concurrency=1,
        resume=True,
    )
    targets = load_evaluation_targets(rubric_config, sources)
    rubric = RubricScoreRunner(rubric_config, targets)
    free = RubricFreeScoreRunner(free_config, targets)
    rubric.preflight()
    free.preflight()
    prepared_rubric = rubric._prepared
    prepared_free = free._prepared
    if prepared_rubric is None or prepared_free is None:
        raise RuntimeError("saved model reconstruction has no accepted native plan")

    rubric_records = {
        path.stem: _read(path)
        for path in (audit / "rubric_score" / "records").glob("*.json")
    }
    model_rubric_jobs = tuple(
        job for job in prepared_rubric.unique_jobs if job.model == model
    )
    if {job.key for job in model_rubric_jobs} - rubric_records.keys():
        raise RuntimeError("saved model has missing rubric-score judgments")
    refs: dict[tuple[str, str, str], dict[tuple[str, int | None], tuple]] = defaultdict(dict)
    rubric_reference_count = 0
    for job in prepared_rubric.jobs:
        if job.model != model:
            continue
        record = rubric_records[job.key]
        reference = {
            **_rubric_score_job_identity(job),
            "judgment_key": job.key,
            **{
                field: record[field]
                for field in (
                    "score",
                    "attempt_id",
                    "validation_path",
                    "evaluation_path",
                )
            },
        }
        key = (job.target.assignment_id, model, job.artifact)
        for role in reference["rubric_roles"]:
            role_key = (role["name"], role["variant_index"])
            if role_key in refs[key]:
                raise RuntimeError("duplicate saved rubric role")
            refs[key][role_key] = (reference, record)
            rubric_reference_count += 1

    absolute_records = {
        path.stem: _read(path)
        for path in (audit / "absolute_score" / "records").glob("*.json")
    }
    pairwise_records = {
        path.stem: _read(path)
        for path in (audit / "pairwise_preference" / "records").glob("*.json")
    }
    absolute_jobs = tuple(
        job for job in prepared_free.unique_absolute_jobs if job.model == model
    )
    pairwise_jobs = tuple(
        job for job in prepared_free.unique_pairwise_jobs if job.model == model
    )
    if {job.key for job in absolute_jobs} - absolute_records.keys():
        raise RuntimeError("saved model has missing absolute-score judgments")
    if {job.key for job in pairwise_jobs} - pairwise_records.keys():
        raise RuntimeError("saved model has missing pairwise judgments")
    quality = {}
    for job in prepared_free.absolute_jobs:
        if job.model != model:
            continue
        record = absolute_records[job.key]
        reference = absolute_score.assignment_reference(job, record)
        key = (job.target.assignment_id, model, job.artifact)
        if key in quality:
            raise RuntimeError("duplicate saved absolute-score reference")
        quality[key] = (reference, record)

    direct = {}
    shared_inputs: dict[object, object] = {}
    for window in RevisionDetectionWindow:
        runner = prepare_direct_detection(
            DirectDetectionConfig(
                experiment=experiment,
                study_dir=study,
                output_dir=audit / f"direct_{window.value}",
                max_concurrency=1,
                resume=True,
                window=window,
            ),
            sources,
            shared_inputs,
        )
        runner.prepare_resume()
        records = {}
        for case in runner.config.source.cases:
            score = (
                runner.config.output_dir
                / "cases"
                / case.case_id
                / model.replace("/", "_")
                / "score.json"
            )
            if not score.is_file():
                raise RuntimeError(
                    f"saved model has missing direct judgment: {window.value}/{case.case_id}"
                )
            record = _read(score)
            if record.get("status") != "completed" or record.get("model") != model:
                raise RuntimeError(f"invalid saved direct judgment: {score}")
            records[(str(case.path), model)] = record
        direct[window.value] = records

    assignments = source_records(study)
    original = recorded_root(study)
    rows = []
    for assignment in assignments:
        aid = str(assignment["assignment_id"])
        assignment_root = study / str(assignment["experiment_dir"])
        state = _read(assignment_root / "state.json")
        submission_id = state["submission_ids"][-1]
        evaluation_path = (
            assignment_root / "rubric-evaluations" / f"{submission_id}.json"
        )
        evaluation = _read(evaluation_path)
        if (
            evaluation.get("kind") != "selected-base-plus-active-penalties-v1"
            or evaluation.get("submission_id") != submission_id
            or evaluation.get("score") != state["scores"][-1]
            or evaluation.get("canonical_original_score")
            != state["fixed_original_scores"][-1]
        ):
            raise RuntimeError("saved score composition differs from terminal state")
        feedback_reference = evaluation["feedback_reference"]
        weak_root = (
            assignment_root
            / "judgments"
            / str(submission_id)
            / str(feedback_reference["rubric_sha256"])
        )
        weak_validation = weak_root / "score_validation.json"
        weak_evaluation = weak_root / "evaluation.json"
        if (
            _digest(weak_validation) != feedback_reference["score_validation_sha256"]
            or _digest(weak_evaluation) != feedback_reference["evaluation_sha256"]
        ):
            raise RuntimeError("saved weak-score evidence changed")
        observations = refs[aid, model, "final"]
        selected = [value for key, value in observations.items() if key[0] == "selected"]
        heldout = [value for key, value in observations.items() if key[0] == "holdout"]
        if len(selected) != 1 or len(heldout) != expected_holdouts:
            raise RuntimeError("saved model selected/holdout coverage differs")
        selected_ref, selected_raw = selected[0]
        if feedback_reference["rubric_sha256"] != selected_raw["rubric_sha256"]:
            raise RuntimeError("selected rubric binding changed")
        original_ref, original_raw = observations["original", None]
        all_refs = [selected[0], *heldout, (original_ref, original_raw)]
        hashes = {raw["submission_content_sha256"] for _reference, raw in all_refs}
        if len(hashes) != 1:
            raise RuntimeError("rubric-score artifacts differ within assignment")
        quality_ref, quality_raw = quality[aid, model, "final"]
        if quality_ref["submission_id"] != submission_id:
            raise RuntimeError("absolute-score submission binding changed")
        W = float(evaluation["reference_score"])
        train = float(evaluation["score"])
        S = float(selected_raw["score"])
        H = mean(float(raw["score"]) for _reference, raw in heldout)
        A = float(quality_raw["verdict"]["score"])
        values = _numeric_scores(W, train, S, H, A)
        initial_selected = [
            value
            for key, value in refs[aid, model, "initial"].items()
            if key[0] == "selected"
        ]
        if len(initial_selected) != 1:
            raise RuntimeError("saved initial selected-rubric coverage differs")
        values.update({
            "quality_gain": A - float(quality[aid, model, "initial"][1]["verdict"]["score"]),
            "selected_gain": S - float(initial_selected[0][1]["score"]),
            "elicited_penalty": float(evaluation["elicited_penalty"]),
        })
        source_path = str(original / str(assignment["experiment_dir"]))
        evidence = {
            window: direct[window][source_path, model]["verdict"]
            for window in WINDOWS
        }
        rows.append({
            "assignment_id": aid,
            "condition_id": assignment["condition_id"],
            "task_id": assignment["task_id"],
            "replicate": assignment["replicate"],
            "model": model,
            "submission_id": submission_id,
            "submission_sha256": next(iter(hashes)),
            "initial_submission_sha256": quality[aid, model, "initial"][1]["submission_content_sha256"],
            "selected_rubric_sha256": selected_raw["rubric_sha256"],
            "values": values,
            "direct": evidence,
            "weak_master": state["fixed_original_scores"][-1],
            "strong_master": original_raw["score"],
            "heldout_values": [raw["score"] for _reference, raw in heldout],
            "retained_revisions": len(state["submission_ids"]) - 1,
            "attempted_turns": len(list((assignment_root / "turns").glob("turn-*"))),
            "stop_reason": state["stop_reason"],
            "generation_round": evaluation["generation_round"],
            "state_path": str(assignment_root / "state.json"),
            "state_sha256": _digest(assignment_root / "state.json"),
            "score_composition_path": str(evaluation_path),
            "score_composition_sha256": _digest(evaluation_path),
        })
    coverage = {
        "assignment_count": len(assignments),
        "audited_models": [model],
        "semantic_judgments": (
            len(model_rubric_jobs)
            + len(absolute_jobs)
            + len(pairwise_jobs)
            + len(assignments) * len(WINDOWS)
        ),
        "stages": {
            "rubric_score": len(model_rubric_jobs),
            "absolute_score": len(absolute_jobs),
            "pairwise_preference": len(pairwise_jobs),
            **{
                f"direct_{window}": len(direct[window]) for window in WINDOWS
            },
        },
        "direct_decisions": {
            window: dict(Counter(
                record["verdict"]["decision"]
                for record in direct[window].values()
            ))
            for window in WINDOWS
        },
        "rubric_assignment_references": rubric_reference_count,
        "source_panel_complete": False,
        "reconstruction": "native-record single-model validation",
    }
    return coverage, rows
