"""Strong-ensemble rescoring against each task's original human rubric."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean, median
from typing import Callable, Iterable, Iterator

from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.runtime.agents.policy import MAX_TRANSIENT_RETRIES
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.judge import (
    SCORING_IDENTITY_KEYS,
    FrozenRubricJudge,
    JudgeArtifacts,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.judging.models import (
    grading_engine_for_benchmark,
)
from rubric_gen.submission_revision.judging.preflight import (
    JudgeDispatchInput,
    preflight_judge_dispatches,
)
from rubric_gen.submission_revision.study import (
    resolve_study_experiment,
    validate_completed_revision,
)
from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.runtime.vllm import normalize_vllm_base_url
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS


SUMMARY_KIND = "original-rubric-ensemble-rescore"
BOUNDARIES = ("initial", "final")


@dataclass(frozen=True)
class OriginalRubricTarget:
    assignment_id: str
    task_id: str
    replicate: int
    condition_id: str
    benchmark: SubmissionBenchmarkId
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
        SubmissionBenchmarkId(self.benchmark)
        if self.review not in {"trace", "trajectory", "workspace"}:
            raise ValueError("review must be trace, trajectory, or workspace")
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
    mechanistic_max_calls: int
    mechanistic_max_request_bytes: int
    mechanistic_max_output_tokens: int

    def __post_init__(self) -> None:
        if not self.targets:
            raise ValueError("original-rubric judging requires assignments")
        assignment_ids = [target.assignment_id for target in self.targets]
        if len(assignment_ids) != len(set(assignment_ids)):
            raise ValueError("original-rubric targets contain duplicate assignments")
        if len({target.benchmark for target in self.targets}) != 1:
            raise ValueError("original-rubric targets must use one benchmark")
        for name, value in (
            ("mechanistic_max_calls", self.mechanistic_max_calls),
            ("mechanistic_max_request_bytes", self.mechanistic_max_request_bytes),
            ("mechanistic_max_output_tokens", self.mechanistic_max_output_tokens),
        ):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be positive")


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
        if self.model not in PRIMARY_RH_MODELS:
            raise ValueError(f"unsupported strong judge model: {self.model}")
        if self.boundary not in BOUNDARIES:
            raise ValueError(f"unsupported boundary: {self.boundary}")

    @property
    def submission(self) -> Path:
        return self.target.submission(self.boundary)

    @property
    def key(self) -> tuple[str, str, str]:
        return self.target.assignment_id, self.model, self.boundary


@dataclass(frozen=True)
class PreparedOriginalRubricJob:
    job: OriginalRubricJob
    semantic_judgment_id: str
    scoring_identity: dict[str, object]
    rubric_text_sha256: str
    review_input_sha256: str
    answer_input_sha256: str


StudyLoader = Callable[[Path], OriginalRubricStudy]
JobOperation = Callable[
    [OriginalRubricEnsembleConfig, OriginalRubricJob],
    dict[str, object],
]
JudgeFactory = Callable[
    [OriginalRubricEnsembleConfig, OriginalRubricJob],
    FrozenRubricJudge,
]


def _load_completed_study(source: Path) -> OriginalRubricStudy:
    source = source.absolute()
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"study must be a regular directory: {source}")
    study = read_json_object(source / "study.json", "study manifest")
    if (
        study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") != "completed"
        or type(study.get("experiment_path")) is not str
        or type(study.get("experiment_id")) is not str
        or type(study.get("seed_run_dir")) is not str
        or type(study.get("paraphrase_run_dir")) is not str
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
    paraphrase_run_dir = Path(str(study["paraphrase_run_dir"]))
    sealed_endpoints = _sealed_study_vllm_endpoints(
        source,
        records,
        experiment.assignments,
    )
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
                    paraphrase_run_dir,
                    vllm_endpoints=sealed_endpoints,
                    judgment_reuse_root=source / "shared-judgments",
                )
            )
            progress.update()
    return OriginalRubricStudy(
        source=source.resolve(),
        experiment_id=experiment.experiment_id,
        targets=tuple(targets),
        mechanistic_max_calls=experiment.outcome_audit[
            "mechanistic_max_calls"
        ],
        mechanistic_max_request_bytes=experiment.outcome_audit[
            "mechanistic_max_request_bytes"
        ],
        mechanistic_max_output_tokens=experiment.outcome_audit[
            "mechanistic_max_output_tokens"
        ],
    )


def _sealed_study_vllm_endpoints(
    source: Path,
    records: dict[str, dict[str, object]],
    assignments: Iterable[dict[str, object]],
) -> dict[str, str]:
    """Reconstruct one consistent historical endpoint map from sealed manifests."""

    routes: dict[str, str | None] = {}

    def bind(
        model: object,
        base_url: object,
        *,
        context: str,
        identity_trailing_slash: bool = False,
    ) -> None:
        if type(model) is not str or not model.strip():
            raise RuntimeError(f"{context} has an invalid model")
        if base_url is not None:
            if type(base_url) is not str or not base_url.strip():
                raise RuntimeError(f"{context} has an invalid base URL")
            try:
                normalized = normalize_vllm_base_url(base_url)
            except ValueError as exc:
                raise RuntimeError(f"{context} has an invalid base URL") from exc
            expected_identity_url = (
                normalized + "/" if identity_trailing_slash else normalized
            )
            if expected_identity_url != base_url:
                raise RuntimeError(f"{context} base URL is not canonical")
            route = normalized
        else:
            route = None
        if model in routes and routes[model] != route:
            raise RuntimeError(
                f"sealed study assigns inconsistent endpoints to model {model}"
            )
        routes[model] = route

    for assignment in assignments:
        assignment_id = str(assignment["assignment_id"])
        experiment_dir = resolve_study_experiment(
            source,
            records[assignment_id],
            assignment,
        )
        manifest = read_json_object(
            experiment_dir / "manifest.json",
            "revision manifest",
        )
        if not {"provider", "model", "solver_base_url"} <= set(manifest):
            raise RuntimeError("revision manifest lacks solver endpoint identity")
        solver_provider = manifest["provider"]
        solver_model = manifest["model"]
        solver_base_url = manifest["solver_base_url"]
        if (
            type(solver_provider) is not str
            or not solver_provider
            or type(solver_model) is not str
            or not solver_model
        ):
            raise RuntimeError("revision manifest has an invalid solver identity")
        if solver_provider == "vllm":
            bind(
                solver_model,
                solver_base_url,
                context="solver",
            )
        elif solver_base_url is not None:
            raise RuntimeError(
                "non-vLLM solver manifest has an unexpected base URL"
            )
        for model_key, base_key, label in (
            ("judge_model", "judge_base_url", "submission judge"),
            (
                "rubric_proposer_model",
                "rubric_proposer_base_url",
                "rubric proposer",
            ),
            (
                "rubric_semantic_judge_model",
                "rubric_semantic_judge_base_url",
                "rubric semantic judge",
            ),
        ):
            if model_key not in manifest or base_key not in manifest:
                raise RuntimeError(f"revision manifest lacks {label} endpoint identity")
            bind(manifest[model_key], manifest[base_key], context=label)
        feedback_simulator = manifest.get("feedback_simulator")
        if feedback_simulator is not None:
            if not isinstance(feedback_simulator, dict):
                raise RuntimeError("revision manifest has invalid feedback simulator")
            bind(
                feedback_simulator.get("model"),
                feedback_simulator.get("base_url"),
                context="feedback simulator",
                identity_trailing_slash=True,
            )
    return {
        model: base_url
        for model, base_url in routes.items()
        if base_url is not None
    }


def _load_completed_target(
    source: Path,
    records: dict[str, dict[str, object]],
    assignment: dict[str, object],
    experiment: Experiment,
    seed_run_dir: Path,
    paraphrase_run_dir: Path,
    *,
    vllm_endpoints: dict[str, str],
    judgment_reuse_root: Path,
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
        paraphrase_run_dir,
        vllm_endpoints=vllm_endpoints,
        judgment_reuse_root=judgment_reuse_root,
    )
    manifest = read_json_object(
        experiment_dir / "manifest.json",
        "revision manifest",
    )
    state = read_json_object(experiment_dir / "state.json", "revision state")
    rubric_name = manifest.get("master_rubric_name")
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
    rubric_sha256 = sha256_file(human_rubric)
    if manifest.get("master_rubric_sha256") != rubric_sha256:
        raise RuntimeError(f"master rubric changed: {experiment_dir}")
    initial_submission = experiment_dir / "submissions" / str(submission_ids[0])
    final_submission = experiment_dir / "submissions" / str(submission_ids[-1])
    return OriginalRubricTarget(
        assignment_id=assignment_id,
        task_id=str(assignment["task_id"]),
        replicate=int(assignment["replicate"]),
        condition_id=str(assignment["condition_id"]),
        benchmark=experiment.benchmark,
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
) -> FrozenRubricJudge:
    judge_config = SubmissionJudgeConfig(
        task_dir=job.target.task_dir,
        experiment_dir=_artifact_experiment_dir(config, job),
        benchmark=job.target.benchmark,
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
    return FrozenRubricJudge(judge_config, rubric)


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validated_scoring_identity(
    judge: FrozenRubricJudge,
    job: OriginalRubricJob,
) -> dict[str, object]:
    identity = judge.scoring_identity()
    expected = {
        "effective_judge_model": job.model,
        "judge_api_base": None,
        "benchmark": job.target.benchmark.value,
        "grading_engine": grading_engine_for_benchmark(
            job.target.benchmark
        ).value,
        "review_mode": job.target.review,
        "max_review_chars": job.target.max_review_chars,
        "rendered_rubric_sha256": job.target.rubric_sha256,
    }
    if (
        type(identity) is not dict
        or set(identity) != set(SCORING_IDENTITY_KEYS)
        or any(identity.get(key) != value for key, value in expected.items())
        or any(
            not _is_sha256(identity.get(key))
            for key in (
                "judge_source_sha256",
                "judge_runner_sha256",
                "scorer_module_sha256",
            )
        )
    ):
        raise RuntimeError("original-rubric scoring identity is invalid")
    return identity


def _prepare_job(
    config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
    build_judge: JudgeFactory,
) -> PreparedOriginalRubricJob:
    judge = build_judge(config, job)
    scoring_identity = _validated_scoring_identity(judge, job)
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
    scoring_identity = _validated_scoring_identity(judge, prepared.job)
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
    scoring_identity = {
        key: validation.get(key) for key in SCORING_IDENTITY_KEYS
    }
    review_input_sha256 = validation.get("review_input_sha256")
    answer_input_sha256 = validation.get("answer_input_sha256")
    if (
        type(score) is not int
        or not 0 <= score <= 100
        or validation.get("effective_judge_model") != job.model
        or validation.get("rendered_rubric_sha256") != job.target.rubric_sha256
        or validation.get("review_mode") != job.target.review
        or not _is_sha256(review_input_sha256)
        or not _is_sha256(answer_input_sha256)
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
        "artifact_attempt_id": _attempt_id(owner),
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
        "artifact_attempt_id": _attempt_id(owner),
        "status": "failed",
        "error": message,
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
        build_judge: JudgeFactory = _build_judge,
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
        has_summary = output_state[1]
        study = self.load_study(study_path)
        jobs = tuple(
            OriginalRubricJob(target, model, boundary)
            for target in study.targets
            for model in PRIMARY_RH_MODELS
            for boundary in BOUNDARIES
        )
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
            if self.config.resume and has_summary
            else []
        )
        retained_keys = {_record_key(record) for record in retained}
        pending_groups: list[tuple[PreparedOriginalRubricJob, ...]] = []
        for group in groups.values():
            present = [item.job.key in retained_keys for item in group]
            if any(present) and not all(present):
                raise RuntimeError(
                    "judge resume summary contains a partial semantic judgment"
                )
            if not any(present):
                pending_groups.append(group)
        records = list(retained)
        self._write_summary(
            study,
            records,
            predispatch_plan=predispatch_plan,
            semantic_judgment_count=len(groups),
            final=False,
        )

        with TerminalProgress(
            total=len(jobs),
            description="original-rubric ensemble judging",
            unit="judgment",
        ) as progress:
            for _record in retained:
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
                    owner = group[0].job
                    try:
                        completed = future.result()
                        self._check_base_completed_record(
                            completed,
                            group[0],
                        )
                        new_records = [
                            _completed_reference_record(completed, item, owner)
                            for item in group
                        ]
                    except Exception as exc:
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
        self._write_summary(
            study,
            records,
            predispatch_plan=predispatch_plan,
            semantic_judgment_count=len(groups),
            final=True,
        )
        return int(any(record["status"] == "failed" for record in records))

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
        outer_attempt_limit = self.config.max_retries + 1
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
            "max_retries": self.config.max_retries,
        }

    def _retained_records(
        self,
        study: OriginalRubricStudy,
        jobs: tuple[OriginalRubricJob, ...],
        groups: dict[str, tuple[PreparedOriginalRubricJob, ...]],
        predispatch_plan: dict[str, object],
    ) -> list[dict[str, object]]:
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
        jobs_by_key = {job.key: job for job in jobs}
        prepared_by_key = {
            prepared.job.key: prepared
            for group in groups.values()
            for prepared in group
        }
        expected_group_keys = {
            semantic_id: {prepared.job.key for prepared in group}
            for semantic_id, group in groups.items()
        }
        values_by_semantic_id: dict[str, list[dict[str, object]]] = {}
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
                prepared = prepared_by_key[key]
                owner = groups[prepared.semantic_judgment_id][0].job
                if not self._has_reference_identity(value, prepared, owner):
                    raise RuntimeError(
                        "judge resume summary contains an invalid semantic reference"
                    )
                status = value.get("status")
                if status == "failed":
                    progress.update()
                elif status == "completed":
                    progress.update()
                else:
                    raise RuntimeError(
                        "judge resume summary contains an invalid status"
                    )
                values_by_semantic_id.setdefault(
                    prepared.semantic_judgment_id,
                    [],
                ).append(value)

        retained: list[dict[str, object]] = []
        for semantic_id, values in values_by_semantic_id.items():
            observed_keys = {_record_key(value) for value in values}
            if observed_keys != expected_group_keys[semantic_id]:
                raise RuntimeError(
                    "judge resume summary contains a partial semantic judgment"
                )
            statuses = {value.get("status") for value in values}
            if statuses == {"failed"}:
                continue
            if statuses != {"completed"}:
                raise RuntimeError(
                    "judge resume semantic judgment has inconsistent statuses"
                )
            group = groups[semantic_id]
            owner = group[0].job
            validated = self.validate_job(self.config, owner)
            self._check_base_completed_record(validated, group[0])
            expected_values = {
                item.job.key: _completed_reference_record(validated, item, owner)
                for item in group
            }
            for value in values:
                key = _record_key(value)
                if expected_values[key] != value:
                    raise RuntimeError(
                        "judge resume record differs from its sealed artifacts"
                    )
                retained.append(value)
        return retained

    @staticmethod
    def _check_base_completed_record(
        record: dict[str, object],
        prepared: PreparedOriginalRubricJob,
    ) -> None:
        job = prepared.job
        if (
            record.get("status") != "completed"
            or _record_key(record) != job.key
            or type(record.get("score")) is not int
            or not 0 <= int(record["score"]) <= 100
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
            "artifact_attempt_id": _attempt_id(owner),
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
        records.sort(key=_record_sort_key)
        assignment_summaries = self._assignment_summaries(study, records)
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
            for model in PRIMARY_RH_MODELS:
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
            if len(complete_scores) != len(PRIMARY_RH_MODELS):
                ensemble = {"status": "incomplete"}
            else:
                initial_scores = [item[0] for item in complete_scores]
                final_scores = [item[1] for item in complete_scores]
                votes = [
                    str(judges[model]["winner"])
                    for model in PRIMARY_RH_MODELS
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
