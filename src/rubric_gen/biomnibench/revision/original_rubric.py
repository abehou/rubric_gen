"""Strong-ensemble rescoring against each task's original human rubric."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Callable

from rubric_gen.biomnibench.agent.prompts import MAX_TRANSIENT_RETRIES
from rubric_gen.biomnibench.experiment import Experiment, load_experiment
from rubric_gen.biomnibench.revision.artifacts import read_json_object
from rubric_gen.biomnibench.revision.judge import (
    BiomniSubmissionJudge,
    JudgeArtifacts,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.biomnibench.study import (
    resolve_study_experiment,
    validate_completed_revision,
)
from rubric_gen.biomnibench.utils.hashing import sha256_file
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.malt.model_judge import STRONG_JUDGE_MODELS


SUMMARY_KIND = "original-rubric-ensemble-rescore"
BOUNDARIES = ("initial", "final")


@dataclass(frozen=True)
class OriginalRubricTarget:
    assignment_id: str
    task_id: str
    replicate: int
    condition_id: str
    experiment_dir: Path
    task_dir: Path
    rubric_name: str
    rubric_sha256: str
    review: str
    max_review_chars: int | None
    initial_submission: Path
    final_submission: Path

    def __post_init__(self) -> None:
        for name, value in (
            ("assignment_id", self.assignment_id),
            ("task_id", self.task_id),
            ("condition_id", self.condition_id),
            ("rubric_name", self.rubric_name),
        ):
            if (
                type(value) is not str
                or not value
                or Path(value).name != value
                or value in {".", ".."}
            ):
                raise ValueError(f"{name} must be a safe non-empty basename")
        if type(self.replicate) is not int or self.replicate < 1:
            raise ValueError("replicate must be positive")
        if self.review not in {"trace", "trajectory"}:
            raise ValueError("review must be trace or trajectory")
        if (
            type(self.rubric_sha256) is not str
            or len(self.rubric_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.rubric_sha256)
        ):
            raise ValueError("rubric_sha256 must be lowercase SHA-256")

    def submission(self, boundary: str) -> Path:
        if boundary == "initial":
            return self.initial_submission
        if boundary == "final":
            return self.final_submission
        raise ValueError(f"unsupported submission boundary: {boundary}")


@dataclass(frozen=True)
class OriginalRubricStudy:
    source: Path
    experiment_id: str
    targets: tuple[OriginalRubricTarget, ...]

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("original-rubric judging requires assignments")
        assignment_ids = [target.assignment_id for target in self.targets]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("original-rubric targets contain duplicate assignments")


@dataclass(frozen=True)
class OriginalRubricEnsembleConfig:
    study_dir: Path
    output_dir: Path
    max_concurrency: int = 3
    max_retries: int = 1
    resume: bool = False

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if (
            type(self.max_retries) is not int
            or not 0 <= self.max_retries <= MAX_TRANSIENT_RETRIES
        ):
            raise ValueError(
                f"max_retries must be between 0 and {MAX_TRANSIENT_RETRIES}"
            )
        if type(self.resume) is not bool:
            raise ValueError("resume must be a boolean")


@dataclass(frozen=True)
class OriginalRubricJob:
    target: OriginalRubricTarget
    model: str
    boundary: str

    def __post_init__(self) -> None:
        if self.model not in STRONG_JUDGE_MODELS:
            raise ValueError(f"unsupported strong judge model: {self.model}")
        if self.boundary not in BOUNDARIES:
            raise ValueError(f"unsupported boundary: {self.boundary}")

    @property
    def submission(self) -> Path:
        return self.target.submission(self.boundary)

    @property
    def key(self) -> tuple[str, str, str]:
        return self.target.assignment_id, self.model, self.boundary


StudyLoader = Callable[[Path], OriginalRubricStudy]
JobOperation = Callable[
    [OriginalRubricEnsembleConfig, OriginalRubricJob],
    dict[str, object],
]


def _load_completed_study(source: Path) -> OriginalRubricStudy:
    source = source.absolute()
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"study must be a regular directory: {source}")
    study = read_json_object(source / "study.json", "study manifest")
    if (
        study.get("schema_version") != 1
        or study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") != "completed"
        or type(study.get("experiment_path")) is not str
        or type(study.get("experiment_id")) is not str
        or type(study.get("seed_run_dir")) is not str
        or type(study.get("records")) is not list
        or any(type(record) is not dict for record in study["records"])
    ):
        raise ValueError(f"study is not a completed randomized revision: {source}")
    experiment = load_experiment(Path(str(study["experiment_path"])))
    if study["experiment_id"] != experiment.experiment_id:
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

    seed_run_dir = Path(str(study["seed_run_dir"]))
    targets: list[OriginalRubricTarget] = []
    with TerminalProgress(
        total=len(experiment.assignments),
        description="validating original-rubric study",
        unit="assignment",
    ) as progress:
        for assignment in experiment.assignments:
            targets.append(
                _load_completed_target(
                    source,
                    records,
                    assignment,
                    experiment,
                    seed_run_dir,
                )
            )
            progress.update()
    return OriginalRubricStudy(
        source=source.resolve(),
        experiment_id=experiment.experiment_id,
        targets=tuple(targets),
    )


def _load_completed_target(
    source: Path,
    records: dict[str, dict[str, object]],
    assignment: dict[str, object],
    experiment: Experiment,
    seed_run_dir: Path,
) -> OriginalRubricTarget:
    assignment_id = str(assignment["assignment_id"])
    experiment_dir = resolve_study_experiment(
        source,
        records[assignment_id],
        assignment,
    )
    validate_completed_revision(
        experiment_dir,
        assignment,
        experiment,
        seed_run_dir,
    )
    manifest = read_json_object(
        experiment_dir / "manifest.json",
        "revision manifest",
    )
    state = read_json_object(experiment_dir / "state.json", "revision state")
    rubric_name = manifest.get("rubric_name")
    task_dir_value = manifest.get("task_dir")
    submission_ids = state.get("submission_ids")
    if (
        type(rubric_name) is not str
        or Path(rubric_name).name != rubric_name
        or type(task_dir_value) is not str
        or type(submission_ids) is not list
        or len(submission_ids) < 2
        or any(type(value) is not str for value in submission_ids)
        or submission_ids[0] != "s000"
    ):
        raise RuntimeError(f"revision has invalid judge inputs: {experiment_dir}")
    task_dir = Path(task_dir_value)
    human_rubric = task_dir / "tests" / rubric_name
    archived_original = experiment_dir / "rubric" / "r0000.txt"
    rubric_sha256 = sha256_file(human_rubric)
    if (
        manifest.get("rubric_sha256") != rubric_sha256
        or sha256_file(archived_original) != rubric_sha256
    ):
        raise RuntimeError(
            f"archived original rubric differs from the human rubric: {experiment_dir}"
        )
    initial_submission = experiment_dir / "submissions" / str(submission_ids[0])
    final_submission = experiment_dir / "submissions" / str(submission_ids[-1])
    return OriginalRubricTarget(
        assignment_id=assignment_id,
        task_id=str(assignment["task_id"]),
        replicate=int(assignment["replicate"]),
        condition_id=str(assignment["condition_id"]),
        experiment_dir=experiment_dir.resolve(),
        task_dir=task_dir.resolve(),
        rubric_name=rubric_name,
        rubric_sha256=rubric_sha256,
        review=str(manifest["review"]),
        max_review_chars=(
            int(manifest["max_review_chars"])
            if manifest["max_review_chars"] is not None
            else None
        ),
        initial_submission=initial_submission.resolve(),
        final_submission=final_submission.resolve(),
    )


def _snapshot_identity(job: OriginalRubricJob) -> dict[str, str]:
    snapshot = read_json_object(
        job.submission / "snapshot.json",
        "submission snapshot",
    )
    identity = {
        "workspace_sha256": snapshot.get("workspace_sha256"),
        "trajectory_sha256": snapshot.get("trajectory_sha256"),
    }
    if any(type(value) is not str or len(value) != 64 for value in identity.values()):
        raise RuntimeError(f"submission snapshot lacks hashes: {job.submission}")
    return {key: str(value) for key, value in identity.items()}


def _attempt_id(job: OriginalRubricJob) -> str:
    payload = {
        "schema_version": 1,
        "kind": SUMMARY_KIND,
        "assignment_id": job.target.assignment_id,
        "model": job.model,
        "boundary": job.boundary,
        "submission_id": job.submission.name,
        "rubric_sha256": job.target.rubric_sha256,
        **_snapshot_identity(job),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _artifact_experiment_dir(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> Path:
    model_id = hashlib.sha256(job.model.encode()).hexdigest()[:16]
    return (
        config.output_dir
        / "artifacts"
        / job.target.assignment_id
        / f"model-{model_id}"
    )


def _build_judge(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> BiomniSubmissionJudge:
    judge_config = SubmissionJudgeConfig(
        task_dir=job.target.task_dir,
        experiment_dir=_artifact_experiment_dir(config, job),
        review=job.target.review,
        judge_model=job.model,
        rubric_name=job.target.rubric_name,
        rubric_set=None,
        max_review_chars=job.target.max_review_chars,
        max_retries=config.max_retries,
    )
    rubric = resolve_optimizer_rubric(judge_config)
    if rubric.sha256 != job.target.rubric_sha256:
        raise RuntimeError("human rubric changed before ensemble judging")
    return BiomniSubmissionJudge(judge_config, rubric)


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
        "attempt_id": _attempt_id(job),
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
    if (
        type(score) is not int
        or not 0 <= score <= 100
        or validation.get("effective_judge_model") != job.model
        or validation.get("rendered_rubric_sha256") != job.target.rubric_sha256
        or validation.get("review_mode") != job.target.review
    ):
        raise RuntimeError("ensemble judge produced an incompatible score validation")
    usage_path = artifacts.score_validation_path.with_name("usage.json")
    for path in (artifacts.score_validation_path, artifacts.evaluation_path, usage_path):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"ensemble judge artifact is missing: {path}")
    return {
        **_job_identity(job),
        "status": "completed",
        "score": score,
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


def _evaluate_job(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> dict[str, object]:
    judge = _build_judge(config, job)
    artifacts = judge.evaluate(job.submission, _attempt_id(job))
    return _completed_record(config, job, artifacts)


def _validate_job(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> dict[str, object]:
    judge = _build_judge(config, job)
    artifacts = judge.validate(job.submission, _attempt_id(job))
    return _completed_record(config, job, artifacts)


def _path_contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _winner(delta: float) -> str:
    if delta > 0:
        return "final"
    if delta < 0:
        return "initial"
    return "tie"


class OriginalRubricEnsembleRunner:
    def __init__(
        self,
        config: OriginalRubricEnsembleConfig,
        *,
        load_study: StudyLoader = _load_completed_study,
        evaluate_job: JobOperation = _evaluate_job,
        validate_job: JobOperation = _validate_job,
    ) -> None:
        self.config = config
        self.load_study = load_study
        self.evaluate_job = evaluate_job
        self.validate_job = validate_job

    def run(self) -> int:
        study_path = self.config.study_dir.resolve()
        output_path = self.config.output_dir.resolve()
        if _path_contains(study_path, output_path) or _path_contains(
            output_path, study_path
        ):
            raise ValueError("judge output and source study must not contain each other")
        study = self.load_study(study_path)
        jobs = tuple(
            OriginalRubricJob(target, model, boundary)
            for target in study.targets
            for model in STRONG_JUDGE_MODELS
            for boundary in BOUNDARIES
        )
        has_summary = self._prepare_output()
        retained = (
            self._retained_records(study, jobs)
            if self.config.resume and has_summary
            else []
        )
        retained_keys = {_record_key(record) for record in retained}
        pending = [job for job in jobs if job.key not in retained_keys]
        records = retained
        self._write_summary(study, records, final=False)

        with TerminalProgress(
            total=len(jobs),
            description="original-rubric ensemble judging",
            unit="judgment",
        ) as progress:
            for _record in retained:
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {pool.submit(self.evaluate_job, self.config, job): job for job in pending}
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        record = future.result()
                        self._check_completed_record(record, job)
                    except Exception as exc:
                        record = {
                            **_job_identity(job),
                            "status": "failed",
                            "error": str(exc),
                        }
                    records.append(record)
                    self._write_summary(study, records, final=False)
                    progress.update()
                    progress.set_status(
                        f"failed={sum(item['status'] == 'failed' for item in records)}"
                    )
        self._write_summary(study, records, final=True)
        return int(any(record["status"] == "failed" for record in records))

    def _prepare_output(self) -> bool:
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
        output.mkdir(parents=True, exist_ok=True)
        return (output / "summary.json").is_file()

    def _protocol(self) -> dict[str, object]:
        return {
            "models": list(STRONG_JUDGE_MODELS),
            "submissions": list(BOUNDARIES),
            "rubric": "original-human-written-r0000",
            "score_scale": [0, 100],
            "numeric_aggregates": ["mean", "median"],
            "direction_aggregate": "strict-majority-of-model-deltas",
            "max_retries": self.config.max_retries,
        }

    def _retained_records(
        self,
        study: OriginalRubricStudy,
        jobs: tuple[OriginalRubricJob, ...],
    ) -> list[dict[str, object]]:
        summary = read_json_object(
            self.config.output_dir / "summary.json",
            "original-rubric judge summary",
        )
        if (
            set(summary) != {
                "schema_version",
                "kind",
                "status",
                "source",
                "protocol",
                "totals",
                "records",
                "assignments",
                "conditions",
            }
            or summary.get("schema_version") != 1
            or summary.get("kind") != SUMMARY_KIND
            or summary.get("source") != {
                "study_dir": str(study.source),
                "experiment_id": study.experiment_id,
                "assignment_count": len(study.targets),
            }
            or summary.get("protocol") != self._protocol()
            or type(summary.get("records")) is not list
        ):
            raise RuntimeError("judge resume summary has incompatible identity")
        jobs_by_key = {job.key: job for job in jobs}
        retained: list[dict[str, object]] = []
        seen: set[tuple[str, str, str]] = set()
        with TerminalProgress(
            total=len(summary["records"]),
            description="validating resumed judgments",
            unit="judgment",
        ) as progress:
            for value in summary["records"]:
                if type(value) is not dict:
                    raise RuntimeError(
                        "judge resume summary contains a non-object record"
                    )
                key = _record_key(value)
                if key in seen or key not in jobs_by_key:
                    raise RuntimeError(
                        "judge resume summary contains an invalid job identity"
                    )
                seen.add(key)
                status = value.get("status")
                if status == "failed":
                    progress.update()
                    continue
                if status != "completed":
                    raise RuntimeError(
                        "judge resume summary contains an invalid status"
                    )
                validated = self.validate_job(self.config, jobs_by_key[key])
                self._check_completed_record(validated, jobs_by_key[key])
                if validated != value:
                    raise RuntimeError(
                        "judge resume record differs from its sealed artifacts"
                    )
                retained.append(validated)
                progress.update()
        return retained

    @staticmethod
    def _check_completed_record(
        record: dict[str, object],
        job: OriginalRubricJob,
    ) -> None:
        if (
            record.get("status") != "completed"
            or _record_key(record) != job.key
            or type(record.get("score")) is not int
            or not 0 <= int(record["score"]) <= 100
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

    def _write_summary(
        self,
        study: OriginalRubricStudy,
        records: list[dict[str, object]],
        *,
        final: bool,
    ) -> None:
        records.sort(key=_record_sort_key)
        assignment_summaries = self._assignment_summaries(study, records)
        complete = sum(record["status"] == "completed" for record in records)
        failed = sum(record["status"] == "failed" for record in records)
        total = len(study.targets) * len(STRONG_JUDGE_MODELS) * len(BOUNDARIES)
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
                "schema_version": 1,
                "kind": SUMMARY_KIND,
                "status": status,
                "source": {
                    "study_dir": str(study.source),
                    "experiment_id": study.experiment_id,
                    "assignment_count": len(study.targets),
                },
                "protocol": self._protocol(),
                "totals": {
                    "jobs": total,
                    "completed": complete,
                    "failed": failed,
                    "pending": total - complete - failed,
                },
                "records": records,
                "assignments": assignment_summaries,
                "conditions": _condition_summaries(assignment_summaries),
            },
        )

    @staticmethod
    def _assignment_summaries(
        study: OriginalRubricStudy,
        records: list[dict[str, object]],
    ) -> dict[str, object]:
        record_map = {_record_key(record): record for record in records}
        summaries: dict[str, object] = {}
        for target in study.targets:
            judges: dict[str, dict[str, object]] = {}
            complete_scores: list[tuple[float, float]] = []
            for model in STRONG_JUDGE_MODELS:
                initial = record_map.get((target.assignment_id, model, "initial"))
                final = record_map.get((target.assignment_id, model, "final"))
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
            ensemble: dict[str, object]
            if len(complete_scores) != len(STRONG_JUDGE_MODELS):
                ensemble = {"status": "incomplete"}
            else:
                initial_scores = [item[0] for item in complete_scores]
                final_scores = [item[1] for item in complete_scores]
                votes = [
                    str(judges[model]["winner"])
                    for model in STRONG_JUDGE_MODELS
                ]
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
            summaries[target.assignment_id] = {
                "task_id": target.task_id,
                "replicate": target.replicate,
                "condition_id": target.condition_id,
                "rubric_sha256": target.rubric_sha256,
                "judges": judges,
                "ensemble": ensemble,
            }
        return summaries


def _record_key(record: dict[str, object]) -> tuple[str, str, str]:
    values = (
        record.get("assignment_id"),
        record.get("model"),
        record.get("boundary"),
    )
    if any(type(value) is not str for value in values):
        raise RuntimeError("ensemble record has an invalid identity")
    return str(values[0]), str(values[1]), str(values[2])


def _record_sort_key(record: dict[str, object]) -> tuple[str, str, int]:
    assignment_id, model, boundary = _record_key(record)
    return assignment_id, model, BOUNDARIES.index(boundary)


def _condition_summaries(assignments: dict[str, object]) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for value in assignments.values():
        if type(value) is not dict:
            continue
        ensemble = value.get("ensemble")
        if type(ensemble) is not dict or ensemble.get("status") != "completed":
            continue
        grouped.setdefault(str(value["condition_id"]), []).append(ensemble)
    summaries: dict[str, object] = {}
    for condition_id, rows in sorted(grouped.items()):
        summaries[condition_id] = {
            "assignments": len(rows),
            "initial_mean": fmean(float(row["initial_mean"]) for row in rows),
            "final_mean": fmean(float(row["final_mean"]) for row in rows),
            "mean_delta": fmean(float(row["mean_delta"]) for row in rows),
            "final_majority_win_rate": fmean(
                row["majority_winner"] == "final" for row in rows
            ),
        }
    return summaries
