"""Load original-rubric study inputs and define exact job contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.runtime.vllm import normalize_vllm_base_url
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.judge import (
    SCORING_IDENTITY_KEYS,
    FrozenRubricJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.judging.models import (
    grading_engine_for_benchmark,
)
from rubric_gen.submission_revision.study_layout import resolve_study_experiment
from rubric_gen.submission_revision.study_validation import validate_completed_revision


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
    resume: bool = False

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
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


def load_completed_original_rubric_study(source: Path) -> OriginalRubricStudy:
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
        _bind_manifest_endpoints(routes, manifest)
    return {
        model: base_url
        for model, base_url in routes.items()
        if base_url is not None
    }


def _bind_manifest_endpoints(
    routes: dict[str, str | None],
    manifest: dict[str, object],
) -> None:
    if not {"provider", "model", "solver_base_url"} <= set(manifest):
        raise RuntimeError("revision manifest lacks solver endpoint identity")
    provider = manifest["provider"]
    model = manifest["model"]
    base_url = manifest["solver_base_url"]
    if type(provider) is not str or not provider or type(model) is not str or not model:
        raise RuntimeError("revision manifest has an invalid solver identity")
    if provider == "vllm":
        _bind_endpoint_route(routes, model, base_url, context="solver")
    elif base_url is not None:
        raise RuntimeError("non-vLLM solver manifest has an unexpected base URL")
    _bind_judge_endpoints(routes, manifest)
    _bind_feedback_simulator_endpoint(routes, manifest.get("feedback_simulator"))


def _bind_judge_endpoints(
    routes: dict[str, str | None],
    manifest: dict[str, object],
) -> None:
    for model_key, base_key, label in (
        ("judge_model", "judge_base_url", "submission judge"),
        ("rubric_proposer_model", "rubric_proposer_base_url", "rubric proposer"),
        (
            "rubric_semantic_judge_model",
            "rubric_semantic_judge_base_url",
            "rubric semantic judge",
        ),
    ):
        if model_key not in manifest or base_key not in manifest:
            raise RuntimeError(f"revision manifest lacks {label} endpoint identity")
        _bind_endpoint_route(
            routes,
            manifest[model_key],
            manifest[base_key],
            context=label,
        )


def _bind_feedback_simulator_endpoint(
    routes: dict[str, str | None],
    feedback_simulator: object,
) -> None:
    if feedback_simulator is None:
        return
    if not isinstance(feedback_simulator, dict):
        raise RuntimeError("revision manifest has invalid feedback simulator")
    _bind_endpoint_route(
        routes,
        feedback_simulator.get("model"),
        feedback_simulator.get("base_url"),
        context="feedback simulator",
        identity_trailing_slash=True,
    )


def _bind_endpoint_route(
    routes: dict[str, str | None],
    model: object,
    base_url: object,
    *,
    context: str,
    identity_trailing_slash: bool = False,
) -> None:
    if type(model) is not str or not model.strip():
        raise RuntimeError(f"{context} has an invalid model")
    route = _canonical_endpoint_route(
        base_url,
        context=context,
        identity_trailing_slash=identity_trailing_slash,
    )
    if model in routes and routes[model] != route:
        raise RuntimeError(
            f"sealed study assigns inconsistent endpoints to model {model}"
        )
    routes[model] = route


def _canonical_endpoint_route(
    base_url: object,
    *,
    context: str,
    identity_trailing_slash: bool,
) -> str | None:
    if base_url is None:
        return None
    if type(base_url) is not str or not base_url.strip():
        raise RuntimeError(f"{context} has an invalid base URL")
    try:
        normalized = normalize_vllm_base_url(base_url)
    except ValueError as exc:
        raise RuntimeError(f"{context} has an invalid base URL") from exc
    expected = normalized + "/" if identity_trailing_slash else normalized
    if expected != base_url:
        raise RuntimeError(f"{context} base URL is not canonical")
    return normalized


def _load_completed_target(
    source: Path,
    records: dict[str, dict[str, object]],
    assignment: dict[str, object],
    experiment: Experiment,
    seed_run_dir: Path,
    paraphrase_run_dir: Path,
    *,
    vllm_endpoints: dict[str, str],
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


def original_rubric_attempt_id(job: OriginalRubricJob) -> str:
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


def build_original_rubric_judge(
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
    )
    rubric = resolve_optimizer_rubric(judge_config)
    if rubric.sha256 != job.target.rubric_sha256:
        raise RuntimeError("human rubric changed before ensemble judging")
    return FrozenRubricJudge(judge_config, rubric)


def is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validated_scoring_identity(
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
            not is_sha256(identity.get(key))
            for key in (
                "scoring_implementation_sha256",
            )
        )
    ):
        raise RuntimeError("original-rubric scoring identity is invalid")
    return identity
