"""Execute and validate a locked randomized revision-study design."""

from __future__ import annotations

import json
import os
import socket
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.experiments import ExperimentDesign, verify_runtime_provenance
from rubric_gen.biomnibench.revision.controller import run_submission_revision
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy, project_feedback
from rubric_gen.biomnibench.revision.models import SubmissionRevisionConfig
from rubric_gen.biomnibench.revision.artifacts import (
    REVISION_MANIFEST_KEYS,
    read_json_object,
    sha256_file,
    verify_submission_snapshot,
)
from rubric_gen.biomnibench.revision.evolution import RubricEvolution
from rubric_gen.biomnibench.revision.seeds import resolve_seed
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


STUDY_RUN_SCHEMA_VERSION = 1
STUDY_RUN_KIND = "rubric-gen-randomized-revision-study"


@dataclass(frozen=True)
class StudyRunConfig:
    design: ExperimentDesign
    seed_run_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool = False

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


class StudyRunner:
    def __init__(self, config: StudyRunConfig) -> None:
        self.config = config
        self.design = config.design
        self.root = config.output_dir.resolve()
        self.seed_root = config.seed_run_dir.resolve()
        self._manifest_lock = threading.Lock()

    def run(self) -> int:
        verify_runtime_provenance(self.design)
        assignments = sorted(
            self.design.assignments,
            key=lambda item: int(item["execution_order"]),
        )
        existed = os.path.lexists(self.root)
        if existed and not self.config.resume:
            raise FileExistsError(f"study output already exists: {self.root}")
        if existed and (self.root.is_symlink() or not self.root.is_dir()):
            raise RuntimeError(f"study output is not a regular directory: {self.root}")
        if not existed:
            self.root.mkdir(parents=True)
            manifest = self._new_manifest(assignments)
            self._write_manifest(manifest)
        else:
            manifest = self._load_manifest()
            self._validate_manifest_identity(manifest, assignments)
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
                        self.design,
                        self.seed_root,
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
                    self.design,
                    self.seed_root,
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
        protocol = self.design.protocol
        condition = self.design.condition(str(assignment["condition_id"]))
        return SubmissionRevisionConfig(
            task_dir=self.design.task_dir(str(assignment["task_id"])),
            experiment_dir=self._experiment_dir(assignment),
            revision_rounds=int(protocol["revision_rounds"]),
            seed_run_dir=self.seed_root,
            agent=self.design.agent_config(),
            run_provenance=self.design.run_provenance,
            design_sha256=self.design.sha256,
            protocol_id=self.design.protocol_id,
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
            rubric_proposer_step_limit=int(protocol["rubric_proposer_step_limit"]),
            review=str(protocol["review"]),
            judge_model=str(protocol["judge_model"]),
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
            "design_path": str(self.design.path),
            "design_sha256": self.design.sha256,
            "protocol_id": self.design.protocol_id,
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
            or manifest.get("design_path") != str(self.design.path)
            or manifest.get("design_sha256") != self.design.sha256
            or manifest.get("protocol_id") != self.design.protocol_id
            or manifest.get("seed_run_dir") != str(self.seed_root)
        ):
            raise RuntimeError("study resume identity differs from the locked design")
        records = _records(manifest)
        if [record.get("assignment_id") for record in records] != [
            item["assignment_id"] for item in assignments
        ]:
            raise RuntimeError("study assignment ledger differs from the design")
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
        raise RuntimeError("design assignment has an unsafe experiment identity")
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
        raise RuntimeError("study record identity differs from its design assignment")
    current = study_root
    for component in expected_relative.parts:
        current = current / component
        if current.is_symlink():
            raise RuntimeError(f"study experiment path contains a symlink: {current}")
    return study_root / expected_relative


def validate_completed_revision(
    experiment_dir: Path,
    assignment: dict[str, object],
    design: ExperimentDesign,
    seed_run_dir: Path,
) -> None:
    if experiment_dir.is_symlink() or not experiment_dir.is_dir():
        raise RuntimeError(f"revision is not a regular directory: {experiment_dir}")
    manifest = read_json_object(experiment_dir / "manifest.json", "revision manifest")
    state = read_json_object(experiment_dir / "state.json", "revision state")
    protocol = design.protocol
    condition_spec = design.condition(str(assignment["condition_id"]))
    agent = design.agent_config()
    task_dir = design.task_dir(str(assignment["task_id"])).resolve()
    seed = resolve_seed(
        seed_run_dir,
        task_dir,
        int(assignment["replicate"]),
        design_sha256=design.sha256,
        protocol_id=design.protocol_id,
        provider=agent.provider,
        requested_model=agent.model,
        run_provenance_sha256=str(design.run_provenance["sha256"]),
    )
    task_records = [
        item
        for item in design.payload["tasks"]  # type: ignore[union-attr]
        if isinstance(item, dict) and item.get("task_id") == assignment["task_id"]
    ]
    if len(task_records) != 1:
        raise RuntimeError("revision task is not uniquely present in the design")
    task_record = task_records[0]
    scoring_identity = seed.manifest.get("scoring_identity")
    if not isinstance(scoring_identity, dict):
        raise RuntimeError("revision seed has invalid scoring identity")
    revision_rounds = int(protocol["revision_rounds"])
    expected_count = revision_rounds + 1
    expected_ids = [f"s{index:03d}" for index in range(expected_count)]
    manifest_expectations = {
        "schema_version": 2,
        "kind": "rubric-gen-submission-revision-experiment",
        "design_sha256": design.sha256,
        "protocol_id": design.protocol_id,
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
        "rubric_proposer_step_limit": protocol["rubric_proposer_step_limit"],
        "rubric_proposer_max_retries": protocol["rubric_proposer_max_retries"],
        "review": protocol["review"],
        "judge_model": protocol["judge_model"],
        "judge_max_retries": protocol["judge_max_retries"],
        "max_review_chars": protocol["max_review_chars"],
        "rubric_name": protocol["rubric_name"],
        "rubric_set": None,
        "rubric_sha256": task_record["rubric_sha256"],
        "instruction_sha256": task_record["instruction_sha256"],
        "data_sha256": task_record["data_sha256"],
        "seed_run_dir": str(seed.root),
        "seed_sha256": seed.sha256,
        "run_provenance": design.run_provenance,
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
    final_prompt: str | None = None
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
        final_prompt = projected.prompt
    if state.get("next_prompt") != final_prompt:
        raise RuntimeError("completed revision next prompt disagrees with feedback")
    condition_id = str(assignment["condition_id"])
    if condition_id.endswith("--prospective"):
        expected_rubrics = [f"r{index:04d}.txt" for index in range(expected_count)]
    else:
        expected_rubrics = ["r0000.txt"]
    observed_rubrics = sorted(
        path.name for path in (experiment_dir / "rubric").glob("r*.txt")
    )
    if observed_rubrics != expected_rubrics:
        raise RuntimeError("revision rubric version set is incomplete")


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
