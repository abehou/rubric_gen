"""Execute and validate a randomized YAML experiment."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import stat
import threading
import traceback
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.experiment import Experiment
from rubric_gen.biomnibench.revision.controller import run_submission_revision
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy, project_feedback
from rubric_gen.biomnibench.revision.models import SubmissionRevisionConfig
from rubric_gen.biomnibench.revision.artifacts import (
    REVISION_MANIFEST_KEYS,
    read_json_object,
    sha256_file,
    tree_sha256,
    verify_submission_snapshot,
)
from rubric_gen.biomnibench.revision.evolution import RubricEvolution
from rubric_gen.biomnibench.revision.seeds import resolve_seed
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


STUDY_RUN_SCHEMA_VERSION = 1
STUDY_RUN_KIND = "rubric-gen-randomized-revision-study"
_STUDY_LEASE_NAME = ".study.lock"


@dataclass(frozen=True)
class StudyRunConfig:
    experiment: Experiment
    seed_run_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool = False
    vllm_endpoints: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


class StudyRunner:
    def __init__(self, config: StudyRunConfig) -> None:
        self.config = config
        self.experiment = config.experiment
        self.root = config.output_dir.resolve()
        self.seed_root = config.seed_run_dir.resolve()
        self._manifest_lock = threading.Lock()

    def run(self) -> int:
        assignments = sorted(
            self.experiment.assignments,
            key=lambda item: int(item["execution_order"]),
        )
        existed = os.path.lexists(self.root)
        if existed and not self.config.resume:
            raise FileExistsError(f"study output already exists: {self.root}")
        if existed and (self.root.is_symlink() or not self.root.is_dir()):
            raise RuntimeError(f"study output is not a regular directory: {self.root}")
        if not existed:
            self.root.mkdir(parents=True)
        with _exclusive_study_lease(self.root):
            return self._run_locked(assignments, existed)

    def _run_locked(
        self,
        assignments: list[dict[str, object]],
        existed: bool,
    ) -> int:
        if not existed:
            manifest = self._new_manifest(assignments)
            self._write_manifest(manifest)
        else:
            manifest = self._load_manifest()
            self._validate_manifest_identity(manifest, assignments)
            _reclaim_interrupted_records(manifest)
        pending: list[dict[str, object]] = []
        for assignment in assignments:
            assignment_id = str(assignment["assignment_id"])
            record = _record_for(manifest, assignment_id)
            experiment = self._experiment_dir(assignment)
            if record.get("status") == "completed":
                try:
                    validate_completed_revision(
                        experiment,
                        assignment,
                        self.experiment,
                        self.seed_root,
                        vllm_endpoints=self.config.vllm_endpoints,
                    )
                except Exception as exc:
                    record.update({
                        "status": "invalid",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })
                continue
            if record.get("status") == "invalid":
                continue
            pending.append(assignment)
        manifest["status"] = "running"
        manifest["finished_at"] = None
        manifest["max_concurrency_last_invocation"] = self.config.max_concurrency
        self._write_manifest(manifest)
        if not pending:
            statuses = {str(record["status"]) for record in _records(manifest)}
            manifest["status"] = (
                "completed" if statuses == {"completed"} else "failed"
            )
            manifest["finished_at"] = _now()
            self._write_manifest(manifest)
            return int(manifest["status"] != "completed")

        positions: list[int] = list(range(1, self.config.max_concurrency + 1))
        position_lock = threading.Lock()

        def acquire_position() -> int:
            with position_lock:
                return positions.pop(0)

        def release_position(position: int) -> None:
            with position_lock:
                positions.append(position)
                positions.sort()

        def execute(assignment: dict[str, object]) -> None:
            position = acquire_position()
            assignment_id = str(assignment["assignment_id"])
            try:
                with self._manifest_lock:
                    latest = self._load_manifest()
                    record = _record_for(latest, assignment_id)
                    record.update({
                        "status": "running",
                        "started_at": _now(),
                        "finished_at": None,
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                        "attempt_count": int(record.get("attempt_count", 0)) + 1,
                    })
                    for key in ("error_type", "error", "traceback"):
                        record.pop(key, None)
                    self._write_manifest(latest)
                experiment = self._experiment_dir(assignment)
                revision = self._revision_config(
                    assignment,
                    resume=os.path.lexists(experiment),
                )
                run_submission_revision(replace(revision, progress_position=position))
                validate_completed_revision(
                    experiment,
                    assignment,
                    self.experiment,
                    self.seed_root,
                    vllm_endpoints=self.config.vllm_endpoints,
                )
                with self._manifest_lock:
                    latest = self._load_manifest()
                    _record_for(latest, assignment_id).update({
                        "status": "completed",
                        "finished_at": _now(),
                    })
                    self._write_manifest(latest)
            except (Exception, SystemExit) as exc:
                with self._manifest_lock:
                    latest = self._load_manifest()
                    _record_for(latest, assignment_id).update({
                        "status": "failed",
                        "finished_at": _now(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    })
                    self._write_manifest(latest)
            finally:
                release_position(position)

        with TerminalProgress(
            total=len(assignments),
            description="randomized study",
            unit="assignment",
            position=0,
        ) as progress:
            for _ in range(len(assignments) - len(pending)):
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = [pool.submit(execute, assignment) for assignment in pending]
                for future in as_completed(futures):
                    future.result()
                    progress.update()
        manifest = self._load_manifest()
        statuses = [str(record["status"]) for record in _records(manifest)]
        manifest["status"] = (
            "completed" if statuses and set(statuses) == {"completed"} else "failed"
        )
        manifest["finished_at"] = _now()
        self._write_manifest(manifest)
        return int(manifest["status"] != "completed")

    def _revision_config(
        self,
        assignment: dict[str, object],
        *,
        resume: bool,
    ) -> SubmissionRevisionConfig:
        protocol = self.experiment.protocol
        condition = self.experiment.condition(str(assignment["condition_id"]))
        return SubmissionRevisionConfig(
            task_dir=self.experiment.task_dir(str(assignment["task_id"])),
            experiment_dir=self._experiment_dir(assignment),
            revision_rounds=int(protocol["revision_rounds"]),
            seed_run_dir=self.seed_root,
            agent=self.experiment.agent_config(
                quiet=True,
                vllm_endpoints=self.config.vllm_endpoints
            ),
            experiment_id=self.experiment.experiment_id,
            assignment_id=str(assignment["assignment_id"]),
            condition_id=str(assignment["condition_id"]),
            replicate=int(assignment["replicate"]),
            execution_order=int(assignment["execution_order"]),
            judge_max_retries=int(protocol["judge_max_retries"]),
            rubric_proposer_max_retries=int(
                protocol["rubric_proposer_max_retries"]
            ),
            feedback_policy=FeedbackPolicy(str(protocol["feedback_policy"])),
            prompt_profile=PromptProfile(str(condition["prompt"])),
            rubric_evolution=RubricEvolution(str(condition["rubric_evolution"])),
            rubric_proposer_model=str(protocol["rubric_proposer_model"]),
            rubric_proposer_base_url=self.config.vllm_endpoints.get(
                str(protocol["rubric_proposer_model"])
            ),
            rubric_proposer_step_limit=int(protocol["rubric_proposer_step_limit"]),
            review=str(protocol["review"]),
            judge_model=str(protocol["judge_model"]),
            judge_base_url=self.config.vllm_endpoints.get(
                str(protocol["judge_model"])
            ),
            rubric_name=str(protocol["rubric_name"]),
            max_review_chars=protocol["max_review_chars"],  # type: ignore[arg-type]
            resume=resume,
            show_progress=True,
            publish_report=False,
        )

    def _experiment_dir(self, assignment: dict[str, object]) -> Path:
        return self.root / study_experiment_relative_path(assignment)

    def _new_manifest(
        self, assignments: list[dict[str, object]]
    ) -> dict[str, object]:
        return {
            "schema_version": STUDY_RUN_SCHEMA_VERSION,
            "kind": STUDY_RUN_KIND,
            "status": "pending",
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "seed_run_dir": str(self.seed_root),
            "started_at": _now(),
            "finished_at": None,
            "max_concurrency_last_invocation": self.config.max_concurrency,
            "records": [
                {
                    "assignment_id": str(item["assignment_id"]),
                    "task_id": str(item["task_id"]),
                    "replicate": int(item["replicate"]),
                    "condition_id": str(item["condition_id"]),
                    "execution_order": int(item["execution_order"]),
                    "experiment_dir": str(self._experiment_dir(item).relative_to(self.root)),
                    "status": "pending",
                    "attempt_count": 0,
                    "started_at": None,
                    "finished_at": None,
                }
                for item in assignments
            ],
        }

    def _load_manifest(self) -> dict[str, object]:
        return read_json_object(self.root / "study.json", "study manifest")

    def _write_manifest(self, manifest: dict[str, object]) -> None:
        write_json_atomic(self.root / "study.json", manifest)

    def _validate_manifest_identity(
        self,
        manifest: dict[str, object],
        assignments: list[dict[str, object]],
    ) -> None:
        if (
            manifest.get("schema_version") != STUDY_RUN_SCHEMA_VERSION
            or manifest.get("kind") != STUDY_RUN_KIND
            or manifest.get("experiment_path") != str(self.experiment.path)
            or manifest.get("experiment_id") != self.experiment.experiment_id
            or manifest.get("seed_run_dir") != str(self.seed_root)
        ):
            raise RuntimeError("study resume identity differs from the experiment")
        records = _records(manifest)
        if [record.get("assignment_id") for record in records] != [
            item["assignment_id"] for item in assignments
        ]:
            raise RuntimeError("study assignment ledger differs from the experiment")
        for record, assignment in zip(records, assignments, strict=True):
            resolve_study_experiment(self.root, record, assignment)


def study_experiment_relative_path(assignment: dict[str, object]) -> Path:
    task_id = assignment.get("task_id")
    replicate = assignment.get("replicate")
    condition_id = assignment.get("condition_id")
    if (
        type(task_id) is not str
        or not task_id
        or Path(task_id).name != task_id
        or type(replicate) is not int
        or replicate < 1
        or type(condition_id) is not str
        or not condition_id
        or Path(condition_id).name != condition_id
    ):
        raise RuntimeError("assignment has an unsafe experiment identity")
    return (
        Path("experiments")
        / task_id
        / f"rep-{replicate:03d}"
        / condition_id
    )


def resolve_study_experiment(
    study_root: Path,
    record: dict[str, object],
    assignment: dict[str, object],
) -> Path:
    expected_relative = study_experiment_relative_path(assignment)
    expected_identity = {
        "assignment_id": assignment.get("assignment_id"),
        "task_id": assignment.get("task_id"),
        "replicate": assignment.get("replicate"),
        "condition_id": assignment.get("condition_id"),
        "execution_order": assignment.get("execution_order"),
        "experiment_dir": expected_relative.as_posix(),
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("study record identity differs from its assignment")
    current = study_root
    for component in expected_relative.parts:
        current = current / component
        if current.is_symlink():
            raise RuntimeError(f"study experiment path contains a symlink: {current}")
    return study_root / expected_relative


def validate_completed_revision(
    experiment_dir: Path,
    assignment: dict[str, object],
    experiment: Experiment,
    seed_run_dir: Path,
    *,
    vllm_endpoints: dict[str, str] | None = None,
) -> None:
    if experiment_dir.is_symlink() or not experiment_dir.is_dir():
        raise RuntimeError(f"revision is not a regular directory: {experiment_dir}")
    manifest = read_json_object(experiment_dir / "manifest.json", "revision manifest")
    state = read_json_object(experiment_dir / "state.json", "revision state")
    protocol = experiment.protocol
    condition_spec = experiment.condition(str(assignment["condition_id"]))
    endpoints = vllm_endpoints or {}
    agent = experiment.agent_config(vllm_endpoints=endpoints)
    task_dir = experiment.task_dir(str(assignment["task_id"])).resolve()
    seed = resolve_seed(
        seed_run_dir,
        task_dir,
        int(assignment["replicate"]),
        experiment_id=experiment.experiment_id,
        provider=agent.provider,
        requested_model=agent.model,
    )
    scoring_identity = seed.manifest.get("scoring_identity")
    if not isinstance(scoring_identity, dict):
        raise RuntimeError("revision seed has invalid scoring identity")
    revision_rounds = int(protocol["revision_rounds"])
    expected_count = revision_rounds + 1
    expected_ids = [f"s{index:03d}" for index in range(expected_count)]
    manifest_expectations = {
        "schema_version": 2,
        "kind": "rubric-gen-submission-revision-experiment",
        "experiment_id": experiment.experiment_id,
        "assignment_id": assignment.get("assignment_id"),
        "condition_id": assignment.get("condition_id"),
        "task_id": assignment.get("task_id"),
        "task_dir": str(task_dir),
        "replicate": assignment.get("replicate"),
        "execution_order": assignment.get("execution_order"),
        "revision_rounds": revision_rounds,
        "provider": agent.provider,
        "model": agent.model,
        "executable": agent.executable,
        "isolation": "codex-custom-permission-profile",
        "command_network_access": False,
        "web_search": False,
        "reasoning_effort": agent.reasoning_effort,
        "service_tier": agent.service_tier,
        "turn_timeout_seconds": agent.timeout_seconds,
        "feedback_policy": protocol["feedback_policy"],
        "prompt": condition_spec["prompt"],
        "rubric_evolution": condition_spec["rubric_evolution"],
        "rubric_proposer_model": protocol["rubric_proposer_model"],
        "rubric_proposer_base_url": endpoints.get(
            str(protocol["rubric_proposer_model"])
        ),
        "rubric_proposer_step_limit": protocol["rubric_proposer_step_limit"],
        "rubric_proposer_max_retries": protocol["rubric_proposer_max_retries"],
        "review": protocol["review"],
        "judge_model": protocol["judge_model"],
        "judge_base_url": endpoints.get(str(protocol["judge_model"])),
        "judge_max_retries": protocol["judge_max_retries"],
        "max_review_chars": protocol["max_review_chars"],
        "rubric_name": protocol["rubric_name"],
        "rubric_set": None,
        "rubric_sha256": sha256_file(task_dir / "tests" / str(protocol["rubric_name"])),
        "instruction_sha256": sha256_file(task_dir / "instruction.md"),
        "data_sha256": tree_sha256(task_dir / "environment" / "data"),
        "seed_run_dir": str(seed.root),
        "seed_sha256": seed.sha256,
        "submission_count": expected_count,
        "live_workspace_removed": True,
        "scoring_identity": scoring_identity,
    }
    if (
        set(manifest) != REVISION_MANIFEST_KEYS
        or any(
            manifest.get(key) != value
            for key, value in manifest_expectations.items()
        )
        or type(manifest.get("live_workspace_dir")) is not str
        or type(manifest.get("session_id")) is not str
        or not manifest["session_id"]
        or type(manifest.get("effective_solver_model")) is not str
        or not manifest["effective_solver_model"]
        or set(state) != {
            "schema_version", "phase", "next_turn_index", "session_id",
            "effective_solver_model", "submission_ids", "scores",
            "judge_attempts", "next_prompt",
        }
        or state.get("schema_version") != 1
        or state.get("phase") != "completed"
        or state.get("submission_ids") != expected_ids
        or state.get("next_turn_index") != expected_count
        or state.get("session_id") != manifest.get("session_id")
        or state.get("effective_solver_model")
        != manifest.get("effective_solver_model")
        or not isinstance(state.get("scores"), list)
        or len(state["scores"]) != expected_count
        or any(
            type(score) is not int or not 0 <= score <= 100
            for score in state["scores"]
        )
        or not isinstance(state.get("judge_attempts"), dict)
        or set(state["judge_attempts"]) != set(expected_ids)
        or any(
            type(attempt) is not str
            or len(attempt) != 32
            or any(character not in "0123456789abcdef" for character in attempt)
            for attempt in state["judge_attempts"].values()
        )
    ):
        raise RuntimeError(f"revision is not complete: {experiment_dir}")
    submissions = experiment_dir / "submissions"
    if submissions.is_symlink() or not submissions.is_dir():
        raise RuntimeError("revision submission root is invalid")
    observed = sorted(path.name for path in submissions.iterdir())
    if observed != expected_ids:
        raise RuntimeError("revision submission set is incomplete")
    feedback_root = experiment_dir / "feedback"
    expected_feedback = [f"{submission_id}.json" for submission_id in expected_ids]
    if (
        feedback_root.is_symlink()
        or not feedback_root.is_dir()
        or sorted(path.name for path in feedback_root.iterdir()) != expected_feedback
    ):
        raise RuntimeError("revision feedback set is incomplete")
    policy = FeedbackPolicy(str(protocol["feedback_policy"]))
    prompt_profile = PromptProfile(str(condition_spec["prompt"]))
    for submission_id in expected_ids:
        submission = submissions / submission_id
        verify_submission_snapshot(submission)
        snapshot = read_json_object(
            submission / "snapshot.json", "submission snapshot"
        )
        status = read_json_object(submission / "status.json", "submission status")
        if snapshot.get("schema_version") != 2 or status.get("schema_version") != 2:
            raise RuntimeError(f"submission uses an invalid schema: {submission_id}")
        feedback = experiment_dir / "feedback" / f"{submission_id}.json"
        if feedback.is_symlink() or not feedback.is_file():
            raise RuntimeError(f"missing feedback for {submission_id}")
        index = int(submission_id[1:])
        rubric_version = (
            0 if condition_spec["rubric_evolution"] == "static" else index
        )
        rubric_path = experiment_dir / "rubric" / f"r{rubric_version:04d}.txt"
        if rubric_path.is_symlink() or not rubric_path.is_file():
            raise RuntimeError(f"missing scoring rubric for {submission_id}")
        if index == 0:
            validation_path, evaluation_path, _ = seed.judgment
        else:
            attempt = str(state["judge_attempts"][submission_id])
            evaluation_root = (
                experiment_dir
                / "evaluations"
                / submission_id
                / sha256_file(rubric_path)
                / attempt
                / "run"
                / "judges"
                / str(protocol["review"])
                / str(assignment["task_id"])
            )
            validation_path = evaluation_root / "score_validation.json"
            evaluation_path = evaluation_root / "evaluation.json"
        if (
            validation_path.is_symlink()
            or evaluation_path.is_symlink()
            or not validation_path.is_file()
            or not evaluation_path.is_file()
        ):
            raise RuntimeError(
                f"scoring artifacts are incomplete for {submission_id}"
            )
        validation_record = read_json_object(
            validation_path, "score validation"
        )
        if (
            validation_record.get("evaluation_sha256")
            != sha256_file(evaluation_path)
        ):
            raise RuntimeError(
                f"evaluation disagrees with score validation: {submission_id}"
            )
        projected = project_feedback(
            validation_path,
            evaluation_path,
            rubric_path.read_text(encoding="utf-8"),
            sha256_file(rubric_path),
            policy,
            prompt_profile=prompt_profile,
        )
        if (
            read_json_object(feedback, "revision feedback") != projected.payload
            or state["scores"][index] != projected.score
        ):
            raise RuntimeError(
                f"feedback disagrees with scoring artifacts: {submission_id}"
            )
    expected_rubrics = _expected_rubric_names(condition_spec, expected_count)
    observed_rubrics = sorted(
        path.name for path in (experiment_dir / "rubric").glob("r*.txt")
    )
    if observed_rubrics != expected_rubrics:
        raise RuntimeError("revision rubric version set is incomplete")


def _expected_rubric_names(
    condition_spec: dict[str, object], submission_count: int
) -> list[str]:
    evolution = RubricEvolution(str(condition_spec["rubric_evolution"]))
    if evolution is RubricEvolution.PROSPECTIVE:
        return [f"r{index:04d}.txt" for index in range(submission_count)]
    return ["r0000.txt"]


@contextmanager
def _exclusive_study_lease(root: Path):
    """Hold the one-writer lease for a study invocation."""

    lock_path = root / _STUDY_LEASE_NAME
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o664)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"study lease is not a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            os.lseek(descriptor, 0, os.SEEK_SET)
            owner = os.read(descriptor, 4096).decode("utf-8", errors="replace").strip()
            detail = f": {owner}" if owner else ""
            raise RuntimeError(f"study already has an active invocation{detail}") from None
        owner = json.dumps(
            {
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "started_at": _now(),
            },
            sort_keys=True,
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, owner + b"\n")
        os.fsync(descriptor)
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reclaim_interrupted_records(manifest: dict[str, object]) -> int:
    """Make records abandoned by the previous leased invocation retryable."""

    reclaimed = 0
    for record in _records(manifest):
        if record.get("status") != "running":
            continue
        owner_hostname = record.get("hostname")
        owner_pid = record.get("pid")
        record.update(
            {
                "status": "failed",
                "finished_at": _now(),
                "error_type": "InterruptedStudyInvocation",
                "error": (
                    "reclaimed assignment from interrupted study invocation "
                    f"on {owner_hostname} pid {owner_pid}"
                ),
            }
        )
        record.pop("traceback", None)
        reclaimed += 1
    return reclaimed


def _records(manifest: dict[str, object]) -> list[dict[str, object]]:
    records = manifest.get("records")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise RuntimeError("study manifest records are invalid")
    return records


def _record_for(manifest: dict[str, object], assignment_id: str) -> dict[str, object]:
    matches = [
        item for item in _records(manifest) if item.get("assignment_id") == assignment_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"study record is missing or duplicated: {assignment_id}")
    return matches[0]


def _now() -> str:
    return datetime.now().astimezone().isoformat()
