"""Build or execute an explicit original-rubric ensemble judgment plan."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median

import yaml

from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.runtime.agents.policy import MAX_TRANSIENT_RETRIES
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.judge import (
    FrozenRubricJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.study import resolve_study_experiment
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.paths import resolve_project_path
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS


PLAN_SCHEMA_VERSION = 1
PLAN_KIND = "rubric-gen-original-rubric-ensemble-plan"
SUMMARY_KIND = "rubric-gen-planned-original-rubric-ensemble"
RUN_KIND = "rubric-gen-original-rubric-ensemble-plan-run"
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_PLAN_KEYS = {
    "schema_version",
    "kind",
    "plan_id",
    "study_dir",
    "output_dir",
    "experiment_id",
    "tasks_dir",
    "review",
    "rubric_name",
    "max_review_chars",
    "models",
    "max_retries",
    "expected",
    "targets",
}
_TARGET_KEYS = {
    "target_id",
    "boundary",
    "task_id",
    "replicate",
    "source_assignment_id",
    "assignment_ids",
    "submission_id",
    "submission_dir",
    "rubric_sha256",
}


@dataclass(frozen=True)
class PlannedTarget:
    target_id: str
    boundary: str
    task_id: str
    replicate: int
    source_assignment_id: str
    assignment_ids: tuple[str, ...]
    submission_id: str
    submission_dir: Path
    task_dir: Path
    rubric_sha256: str


@dataclass(frozen=True)
class JudgmentPlan:
    path: Path
    sha256: str
    plan_id: str
    study_dir: Path
    output_dir: Path
    experiment_id: str
    tasks_dir: Path
    review: str
    rubric_name: str
    max_review_chars: int | None
    models: tuple[str, ...]
    max_retries: int
    expected: dict[str, int]
    targets: tuple[PlannedTarget, ...]
    assignments: dict[str, dict[str, object]]


def _safe_component(value: object, name: str) -> str:
    if type(value) is not str or _SAFE_COMPONENT.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe non-empty component")
    return value


def _snapshot_identity(submission: Path) -> tuple[str, str]:
    if submission.is_symlink() or not submission.is_dir():
        raise RuntimeError(
            f"submission boundary is not a regular directory: {submission}"
        )
    for path, directory in (
        (submission / "snapshot.json", False),
        (submission / "status.json", False),
        (submission / "trajectory.stream.jsonl", False),
        (submission / "workspace", True),
    ):
        invalid_type = not path.is_dir() if directory else not path.is_file()
        if path.is_symlink() or invalid_type:
            raise RuntimeError(f"submission boundary input is invalid: {path}")
    snapshot = read_json_object(submission / "snapshot.json", "submission snapshot")
    values = snapshot.get("workspace_sha256"), snapshot.get("trajectory_sha256")
    if (
        snapshot.get("schema_version") != 2
        or snapshot.get("submission_id") != submission.name
        or any(
            type(value) is not str
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in values
        )
    ):
        raise RuntimeError(f"submission snapshot has invalid hashes: {submission}")
    return str(values[0]), str(values[1])


def _study_inputs(study_dir: Path) -> tuple[
    dict[str, object],
    Experiment,
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    study = read_json_object(study_dir / "study.json", "study manifest")
    if (
        study.get("schema_version") != 1
        or study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") != "completed"
        or type(study.get("experiment_path")) is not str
        or type(study.get("records")) is not list
        or any(type(record) is not dict for record in study["records"])
    ):
        raise ValueError(f"study is not a completed randomized revision: {study_dir}")
    experiment = load_experiment(Path(str(study["experiment_path"])))
    if study.get("experiment_id") != experiment.experiment_id:
        raise ValueError("study experiment identity changed")
    assignments = {
        str(assignment["assignment_id"]): assignment
        for assignment in experiment.assignments
    }
    records = {
        str(record.get("assignment_id")): record
        for record in study["records"]
    }
    if (
        len(records) != len(study["records"])
        or set(records) != set(assignments)
        or any(record.get("status") != "completed" for record in records.values())
    ):
        raise ValueError("study ledger is incomplete or differs from its experiment")
    return study, experiment, assignments, records


def build_plan_payload(
    study_dir: Path,
    output_dir: Path,
    *,
    plan_id: str,
) -> dict[str, object]:
    study_value = study_dir.as_posix()
    output_value = output_dir.as_posix()
    study_dir = resolve_project_path(study_dir).resolve()
    output_dir = resolve_project_path(output_dir).resolve()
    _safe_component(plan_id, "plan_id")
    _study, experiment, assignments, records = _study_inputs(study_dir)
    protocol = experiment.protocol
    rubric_name = _safe_component(protocol["rubric_name"], "rubric_name")
    groups: dict[tuple[str, int], list[dict[str, object]]] = {}
    for assignment in assignments.values():
        key = str(assignment["task_id"]), int(assignment["replicate"])
        groups.setdefault(key, []).append(assignment)

    targets: list[dict[str, object]] = []
    for (task_id, replicate), group in sorted(groups.items()):
        ordered = sorted(group, key=lambda value: str(value["condition_id"]))
        preferred = [
            value for value in ordered if value["condition_id"] == "base-static"
        ]
        source = (preferred or ordered)[0]
        source_id = str(source["assignment_id"])
        source_experiment = resolve_study_experiment(
            study_dir,
            records[source_id],
            source,
        )
        initial = source_experiment / "submissions" / "s000"
        initial_identity = _snapshot_identity(initial)
        assignment_ids = tuple(str(value["assignment_id"]) for value in ordered)
        for assignment in ordered:
            assignment_id = str(assignment["assignment_id"])
            experiment_dir = resolve_study_experiment(
                study_dir,
                records[assignment_id],
                assignment,
            )
            if _snapshot_identity(experiment_dir / "submissions" / "s000") != (
                initial_identity
            ):
                raise RuntimeError(
                    "initial submission differs across randomized conditions: "
                    f"{task_id} replicate {replicate}"
                )
        task_dir = experiment.task_dir(task_id).resolve()
        rubric_sha256 = sha256_file(task_dir / "tests" / rubric_name)
        targets.append({
            "target_id": f"{task_id}--rep-{replicate:03d}--initial",
            "boundary": "initial",
            "task_id": task_id,
            "replicate": replicate,
            "source_assignment_id": source_id,
            "assignment_ids": list(assignment_ids),
            "submission_id": "s000",
            "submission_dir": initial.relative_to(study_dir).as_posix(),
            "rubric_sha256": rubric_sha256,
        })
        for assignment in ordered:
            assignment_id = str(assignment["assignment_id"])
            experiment_dir = resolve_study_experiment(
                study_dir,
                records[assignment_id],
                assignment,
            )
            state = read_json_object(experiment_dir / "state.json", "revision state")
            submission_ids = state.get("submission_ids")
            if (
                type(submission_ids) is not list
                or not submission_ids
                or submission_ids[-1] != "s010"
            ):
                raise RuntimeError(
                    f"planned study does not end at s010: {assignment_id}"
                )
            final = experiment_dir / "submissions" / "s010"
            targets.append({
                "target_id": f"{assignment_id}--final",
                "boundary": "final",
                "task_id": task_id,
                "replicate": replicate,
                "source_assignment_id": assignment_id,
                "assignment_ids": [assignment_id],
                "submission_id": "s010",
                "submission_dir": final.relative_to(study_dir).as_posix(),
                "rubric_sha256": rubric_sha256,
            })

    initial_count = sum(target["boundary"] == "initial" for target in targets)
    final_count = sum(target["boundary"] == "final" for target in targets)
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "plan_id": plan_id,
        "study_dir": study_value,
        "output_dir": output_value,
        "experiment_id": experiment.experiment_id,
        "tasks_dir": str(experiment.tasks_dir.resolve()),
        "review": str(protocol["review"]),
        "rubric_name": rubric_name,
        "max_review_chars": protocol["max_review_chars"],
        "models": list(PRIMARY_RH_MODELS),
        "max_retries": 1,
        "expected": {
            "assignments": len(assignments),
            "initial_targets": initial_count,
            "final_targets": final_count,
            "score_targets": len(targets),
            "hosted_calls": len(targets) * len(PRIMARY_RH_MODELS),
        },
        "targets": targets,
    }


def write_plan(
    path: Path,
    study_dir: Path,
    output_dir: Path,
    *,
    plan_id: str,
) -> None:
    payload = build_plan_payload(study_dir, output_dir, plan_id=plan_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, width=100),
        encoding="utf-8",
    )


def load_plan(path: Path) -> JudgmentPlan:
    path = path.resolve()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"judgment plan is not valid YAML: {path}") from exc
    if type(raw) is not dict or set(raw) != _PLAN_KEYS:
        raise ValueError("judgment plan has an invalid top-level schema")
    if raw.get("schema_version") != PLAN_SCHEMA_VERSION or raw.get("kind") != PLAN_KIND:
        raise ValueError("judgment plan has an unsupported identity")
    plan_id = _safe_component(raw.get("plan_id"), "plan_id")
    study_dir = resolve_project_path(str(raw["study_dir"])).resolve()
    output_dir = resolve_project_path(str(raw["output_dir"])).resolve()
    tasks_dir = resolve_project_path(str(raw["tasks_dir"])).resolve()
    if study_dir == output_dir or study_dir in output_dir.parents or output_dir in study_dir.parents:
        raise ValueError("plan study and output directories must not contain each other")
    _study, experiment, assignments, records = _study_inputs(study_dir)
    if raw.get("experiment_id") != experiment.experiment_id:
        raise ValueError("plan experiment identity changed")
    if tasks_dir != experiment.tasks_dir.resolve():
        raise ValueError("plan task directory changed")
    review = raw.get("review")
    rubric_name = _safe_component(raw.get("rubric_name"), "rubric_name")
    max_review_chars = raw.get("max_review_chars")
    models = raw.get("models")
    max_retries = raw.get("max_retries")
    expected = raw.get("expected")
    raw_targets = raw.get("targets")
    if (
        type(review) is not str
        or review not in {"trace", "trajectory"}
        or (
            max_review_chars is not None
            and (type(max_review_chars) is not int or max_review_chars < 1)
        )
        or models != list(PRIMARY_RH_MODELS)
        or type(max_retries) is not int
        or not 0 <= max_retries <= MAX_TRANSIENT_RETRIES
        or type(expected) is not dict
        or set(expected) != {
            "assignments",
            "initial_targets",
            "final_targets",
            "score_targets",
            "hosted_calls",
        }
        or any(type(value) is not int or value < 1 for value in expected.values())
        or type(raw_targets) is not list
        or any(type(value) is not dict for value in raw_targets)
    ):
        raise ValueError("judgment plan has invalid protocol fields")

    targets: list[PlannedTarget] = []
    initial_coverage: list[str] = []
    final_coverage: list[str] = []
    target_ids: set[str] = set()
    human_rubrics: dict[str, str] = {}
    experiment_groups = {
        (str(assignment["task_id"]), int(assignment["replicate"]))
        for assignment in assignments.values()
    }
    condition_ids = {
        str(assignment["condition_id"])
        for assignment in assignments.values()
    }
    with TerminalProgress(
        total=len(raw_targets),
        description="validating planned judge targets",
        unit="target",
    ) as progress:
        for value in raw_targets:
            if set(value) != _TARGET_KEYS:
                raise ValueError("judgment plan target has an invalid schema")
            target_id = _safe_component(value["target_id"], "target_id")
            boundary = value["boundary"]
            task_id = _safe_component(value["task_id"], "task_id")
            replicate = value["replicate"]
            source_id = _safe_component(
                value["source_assignment_id"], "source_assignment_id"
            )
            assignment_ids_value = value["assignment_ids"]
            submission_id = _safe_component(value["submission_id"], "submission_id")
            rubric_sha256 = value["rubric_sha256"]
            if (
                target_id in target_ids
                or boundary not in {"initial", "final"}
                or type(replicate) is not int
                or replicate < 1
                or type(assignment_ids_value) is not list
                or not assignment_ids_value
                or any(type(item) is not str for item in assignment_ids_value)
                or len(assignment_ids_value) != len(set(assignment_ids_value))
                or source_id not in assignment_ids_value
                or type(rubric_sha256) is not str
                or len(rubric_sha256) != 64
                or any(character not in "0123456789abcdef" for character in rubric_sha256)
            ):
                raise ValueError(f"judgment plan target is invalid: {target_id}")
            assignment_ids = tuple(
                _safe_component(item, "assignment_id")
                for item in assignment_ids_value
            )
            if any(item not in assignments for item in assignment_ids):
                raise ValueError(f"plan target names an unknown assignment: {target_id}")
            mapped = [assignments[item] for item in assignment_ids]
            if any(
                item["task_id"] != task_id or item["replicate"] != replicate
                for item in mapped
            ):
                raise ValueError(f"plan target crosses task-replicate groups: {target_id}")
            if boundary == "initial":
                if submission_id != "s000":
                    raise ValueError("initial plan targets must select s000")
                if {
                    str(assignment["condition_id"])
                    for assignment in mapped
                } != condition_ids:
                    raise ValueError(
                        "initial plan target must map every randomized condition"
                    )
                initial_coverage.extend(assignment_ids)
            else:
                if len(assignment_ids) != 1 or submission_id != "s010":
                    raise ValueError("final plan targets must select one s010")
                final_coverage.extend(assignment_ids)

            source_assignment = assignments[source_id]
            experiment_dir = resolve_study_experiment(
                study_dir,
                records[source_id],
                source_assignment,
            )
            expected_submission = experiment_dir / "submissions" / submission_id
            relative_value = value["submission_dir"]
            if type(relative_value) is not str:
                raise ValueError("plan submission_dir must be a relative path")
            relative = Path(relative_value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("plan submission_dir is unsafe")
            submission = study_dir / relative
            if submission.absolute() != expected_submission.absolute():
                raise ValueError(f"plan submission path changed: {target_id}")
            status = read_json_object(submission / "status.json", "submission status")
            if (
                status.get("schema_version") != 2
                or status.get("task") != task_id
                or status.get("submission_id") != submission_id
                or status.get("exit_code") != 0
            ):
                raise RuntimeError(f"plan submission status is invalid: {target_id}")
            source_identity = _snapshot_identity(submission)
            if boundary == "initial":
                for assignment_id in assignment_ids:
                    assignment = assignments[assignment_id]
                    mapped_experiment = resolve_study_experiment(
                        study_dir,
                        records[assignment_id],
                        assignment,
                    )
                    mapped_submission = mapped_experiment / "submissions" / "s000"
                    if _snapshot_identity(mapped_submission) != source_identity:
                        raise RuntimeError(
                            f"mapped initial submission changed: {target_id}"
                        )
            task_dir = experiment.task_dir(task_id).resolve()
            if task_id not in human_rubrics:
                human_rubrics[task_id] = sha256_file(
                    task_dir / "tests" / rubric_name
                )
            human_hash = human_rubrics[task_id]
            manifest = read_json_object(
                experiment_dir / "manifest.json",
                "revision manifest",
            )
            archived = experiment_dir / "rubric" / "r0000.txt"
            if (
                rubric_sha256 != human_hash
                or manifest.get("rubric_sha256") != human_hash
                or archived.is_symlink()
                or not archived.is_file()
                or sha256_file(archived) != human_hash
            ):
                raise RuntimeError(f"plan original rubric changed: {target_id}")
            targets.append(PlannedTarget(
                target_id=target_id,
                boundary=str(boundary),
                task_id=task_id,
                replicate=replicate,
                source_assignment_id=source_id,
                assignment_ids=assignment_ids,
                submission_id=submission_id,
                submission_dir=submission.resolve(),
                task_dir=task_dir,
                rubric_sha256=rubric_sha256,
            ))
            target_ids.add(target_id)
            progress.update()

    assignment_set = set(assignments)
    observed = {
        "assignments": len(assignments),
        "initial_targets": sum(target.boundary == "initial" for target in targets),
        "final_targets": sum(target.boundary == "final" for target in targets),
        "score_targets": len(targets),
        "hosted_calls": len(targets) * len(PRIMARY_RH_MODELS),
    }
    if (
        observed != expected
        or observed["initial_targets"] != len(experiment_groups)
        or len(initial_coverage) != len(set(initial_coverage))
        or len(final_coverage) != len(set(final_coverage))
        or set(initial_coverage) != assignment_set
        or set(final_coverage) != assignment_set
    ):
        raise ValueError("judgment plan coverage or expected totals changed")
    return JudgmentPlan(
        path=path,
        sha256=sha256_file(path),
        plan_id=plan_id,
        study_dir=study_dir,
        output_dir=output_dir,
        experiment_id=experiment.experiment_id,
        tasks_dir=tasks_dir,
        review=str(review),
        rubric_name=rubric_name,
        max_review_chars=max_review_chars,
        models=tuple(str(model) for model in models),
        max_retries=max_retries,
        expected={str(key): int(value) for key, value in expected.items()},
        targets=tuple(targets),
        assignments=assignments,
    )


def _attempt_id(plan: JudgmentPlan, target: PlannedTarget, model: str) -> str:
    workspace_sha256, trajectory_sha256 = _snapshot_identity(target.submission_dir)
    payload = {
        "schema_version": 1,
        "kind": SUMMARY_KIND,
        "plan_sha256": plan.sha256,
        "target_id": target.target_id,
        "model": model,
        "submission_id": target.submission_id,
        "workspace_sha256": workspace_sha256,
        "trajectory_sha256": trajectory_sha256,
        "rubric_sha256": target.rubric_sha256,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _artifact_root(plan: JudgmentPlan, target: PlannedTarget, model: str) -> Path:
    model_id = hashlib.sha256(model.encode()).hexdigest()[:16]
    return plan.output_dir / "artifacts" / target.target_id / f"model-{model_id}"


def _evaluate(
    plan: JudgmentPlan,
    target: PlannedTarget,
    model: str,
) -> dict[str, object]:
    config = SubmissionJudgeConfig(
        task_dir=target.task_dir,
        experiment_dir=_artifact_root(plan, target, model),
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        review=plan.review,
        judge_model=model,
        rubric_name=plan.rubric_name,
        rubric_set=None,
        max_review_chars=plan.max_review_chars,
        max_retries=plan.max_retries,
    )
    rubric = resolve_optimizer_rubric(config)
    if rubric.sha256 != target.rubric_sha256:
        raise RuntimeError("planned human rubric changed before judging")
    artifacts = FrozenRubricJudge(config, rubric).evaluate(
        target.submission_dir,
        _attempt_id(plan, target, model),
    )
    validation = read_json_object(
        artifacts.score_validation_path,
        "planned score validation",
    )
    score = validation.get("score")
    if (
        type(score) is not int
        or not 0 <= score <= 100
        or validation.get("effective_judge_model") != model
        or validation.get("rendered_rubric_sha256") != target.rubric_sha256
        or validation.get("review_mode") != plan.review
    ):
        raise RuntimeError("planned judge produced an incompatible score")
    usage = artifacts.score_validation_path.with_name("usage.json")
    for path in (artifacts.score_validation_path, artifacts.evaluation_path, usage):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"planned judge artifact is missing: {path}")
    output = plan.output_dir.resolve()

    def relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(output).as_posix()
        except ValueError as exc:
            raise RuntimeError(f"planned judge artifact escaped output: {path}") from exc

    return {
        "target_id": target.target_id,
        "boundary": target.boundary,
        "task_id": target.task_id,
        "replicate": target.replicate,
        "source_assignment_id": target.source_assignment_id,
        "assignment_ids": list(target.assignment_ids),
        "submission_id": target.submission_id,
        "model": model,
        "status": "completed",
        "score": score,
        "score_validation": relative(artifacts.score_validation_path),
        "score_validation_sha256": sha256_file(artifacts.score_validation_path),
        "evaluation": relative(artifacts.evaluation_path),
        "evaluation_sha256": sha256_file(artifacts.evaluation_path),
        "usage": relative(usage),
        "usage_sha256": sha256_file(usage),
    }


def _winner(delta: float) -> str:
    if delta > 0:
        return "final"
    if delta < 0:
        return "initial"
    return "tie"


def _assignment_summaries(
    plan: JudgmentPlan,
    records: list[dict[str, object]],
) -> dict[str, object]:
    record_map = {
        (str(record["target_id"]), str(record["model"])): record
        for record in records
    }
    initial_targets: dict[str, str] = {}
    final_targets: dict[str, str] = {}
    for target in plan.targets:
        destination = initial_targets if target.boundary == "initial" else final_targets
        for assignment_id in target.assignment_ids:
            destination[assignment_id] = target.target_id
    summaries: dict[str, object] = {}
    for assignment_id, assignment in plan.assignments.items():
        judges: dict[str, dict[str, object]] = {}
        complete_scores: list[tuple[float, float]] = []
        for model in plan.models:
            initial = record_map.get((initial_targets[assignment_id], model))
            final = record_map.get((final_targets[assignment_id], model))
            if (
                initial is None
                or final is None
                or initial.get("status") != "completed"
                or final.get("status") != "completed"
            ):
                judges[model] = {"status": "incomplete"}
                continue
            initial_score = float(initial["score"])
            final_score = float(final["score"])
            delta = final_score - initial_score
            judges[model] = {
                "status": "completed",
                "initial_score": initial_score,
                "final_score": final_score,
                "delta": delta,
                "winner": _winner(delta),
            }
            complete_scores.append((initial_score, final_score))
        if len(complete_scores) != len(plan.models):
            ensemble: dict[str, object] = {"status": "incomplete"}
        else:
            initial_scores = [value[0] for value in complete_scores]
            final_scores = [value[1] for value in complete_scores]
            votes = [str(judges[model]["winner"]) for model in plan.models]
            initial_mean = fmean(initial_scores)
            final_mean = fmean(final_scores)
            initial_median = float(median(initial_scores))
            final_median = float(median(final_scores))
            ensemble = {
                "status": "completed",
                "initial_mean": initial_mean,
                "final_mean": final_mean,
                "mean_delta": final_mean - initial_mean,
                "initial_median": initial_median,
                "final_median": final_median,
                "median_delta": final_median - initial_median,
                "majority_winner": (
                    "final"
                    if votes.count("final") >= 2
                    else "initial"
                    if votes.count("initial") >= 2
                    else "tie"
                ),
                "consensus_winner": votes[0] if len(set(votes)) == 1 else None,
            }
        summaries[assignment_id] = {
            "task_id": assignment["task_id"],
            "replicate": assignment["replicate"],
            "condition_id": assignment["condition_id"],
            "initial_target_id": initial_targets[assignment_id],
            "final_target_id": final_targets[assignment_id],
            "judges": judges,
            "ensemble": ensemble,
        }
    return summaries


def _condition_summaries(assignments: dict[str, object]) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for value in assignments.values():
        if type(value) is not dict:
            continue
        ensemble = value.get("ensemble")
        if type(ensemble) is not dict or ensemble.get("status") != "completed":
            continue
        grouped.setdefault(str(value["condition_id"]), []).append(ensemble)
    return {
        condition_id: {
            "assignments": len(rows),
            "initial_mean": fmean(float(row["initial_mean"]) for row in rows),
            "final_mean": fmean(float(row["final_mean"]) for row in rows),
            "mean_delta": fmean(float(row["mean_delta"]) for row in rows),
            "final_majority_win_rate": fmean(
                row["majority_winner"] == "final" for row in rows
            ),
        }
        for condition_id, rows in sorted(grouped.items())
    }


def _write_summary(
    plan: JudgmentPlan,
    records: list[dict[str, object]],
    *,
    final: bool,
) -> None:
    target_order = {
        target.target_id: index for index, target in enumerate(plan.targets)
    }
    model_order = {model: index for index, model in enumerate(plan.models)}
    records.sort(key=lambda record: (
        target_order[str(record["target_id"])],
        model_order[str(record["model"])],
    ))
    complete = sum(record["status"] == "completed" for record in records)
    failed = sum(record["status"] == "failed" for record in records)
    total = plan.expected["hosted_calls"]
    assignments = _assignment_summaries(plan, records)
    write_json_atomic(
        plan.output_dir / "summary.json",
        {
            "schema_version": 1,
            "kind": SUMMARY_KIND,
            "status": (
                "completed"
                if complete == total
                else "failed"
                if final
                else "running"
            ),
            "plan": {
                "path": str(plan.path),
                "sha256": plan.sha256,
                "plan_id": plan.plan_id,
                "study_dir": str(plan.study_dir),
                "experiment_id": plan.experiment_id,
            },
            "protocol": {
                "models": list(plan.models),
                "rubric": "original-human-written-r0000",
                "shared_initial_scoring": "once-per-task-replicate",
                "score_scale": [0, 100],
                "max_retries": plan.max_retries,
            },
            "totals": {
                "jobs": total,
                "completed": complete,
                "failed": failed,
                "pending": total - complete - failed,
            },
            "records": records,
            "assignments": assignments,
            "conditions": _condition_summaries(assignments),
        },
    )


def _prepare_output(plan: JudgmentPlan, *, resume: bool) -> None:
    output = plan.output_dir
    if output.is_symlink() or output.exists() and not output.is_dir():
        raise ValueError(f"plan output must be a regular directory: {output}")
    identity = {
        "schema_version": 1,
        "kind": RUN_KIND,
        "plan_sha256": plan.sha256,
        "plan_id": plan.plan_id,
        "experiment_id": plan.experiment_id,
        "models": list(plan.models),
        "target_count": len(plan.targets),
        "hosted_call_count": plan.expected["hosted_calls"],
    }
    if output.is_dir() and any(output.iterdir()):
        if not resume:
            raise FileExistsError(f"plan output is not empty; use --resume: {output}")
        if read_json_object(output / "run.json", "plan run identity") != identity:
            raise RuntimeError("plan resume output has an incompatible identity")
        return
    output.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output / "run.json", identity)


def run_plan(plan: JudgmentPlan, *, max_concurrency: int, resume: bool) -> int:
    if type(max_concurrency) is not int or max_concurrency < 1:
        raise ValueError("max_concurrency must be positive")
    _prepare_output(plan, resume=resume)
    jobs = [
        (target, model)
        for target in plan.targets
        for model in plan.models
    ]
    records: list[dict[str, object]] = []
    _write_summary(plan, records, final=False)
    with TerminalProgress(
        total=len(jobs),
        description="planned original-rubric ensemble judging",
        unit="judgment",
    ) as progress:
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pool.submit(_evaluate, plan, target, model): (target, model)
                for target, model in jobs
            }
            for future in as_completed(futures):
                target, model = futures[future]
                try:
                    record = future.result()
                except Exception as exc:
                    record = {
                        "target_id": target.target_id,
                        "boundary": target.boundary,
                        "task_id": target.task_id,
                        "replicate": target.replicate,
                        "source_assignment_id": target.source_assignment_id,
                        "assignment_ids": list(target.assignment_ids),
                        "submission_id": target.submission_id,
                        "model": model,
                        "status": "failed",
                        "error": str(exc),
                    }
                records.append(record)
                _write_summary(plan, records, final=False)
                progress.update()
                progress.set_status(
                    f"failed={sum(item['status'] == 'failed' for item in records)}"
                )
    _write_summary(plan, records, final=True)
    return int(any(record["status"] == "failed" for record in records))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Write an explicit YAML plan.")
    build.add_argument("--study-dir", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--plan", required=True)
    build.add_argument("--plan-id", required=True)
    run = subparsers.add_parser("run", help="Execute an explicit YAML plan.")
    run.add_argument("--plan", required=True)
    run.add_argument("--max-concurrency", type=int, default=3)
    run.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        write_plan(
            resolve_project_path(args.plan),
            Path(args.study_dir),
            Path(args.output_dir),
            plan_id=args.plan_id,
        )
        return 0
    plan = load_plan(resolve_project_path(args.plan))
    return run_plan(
        plan,
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )


if __name__ == "__main__":
    raise SystemExit(main())
