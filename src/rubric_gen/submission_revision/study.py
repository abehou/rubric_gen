"""Execute a randomized submission-revision study."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import stat
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.controller import run_submission_revision
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.models import SubmissionRevisionConfig
from rubric_gen.submission_revision import paraphrase_validation
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision import study_layout, study_validation


STUDY_RUN_KIND = "rubric-gen-randomized-revision-study"
_STUDY_LEASE_NAME = ".study.lock"


@dataclass(frozen=True)
class StudyRunConfig:
    experiment: Experiment
    seed_run_dir: Path
    paraphrase_run_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool = False

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


class _ProgressPositions:
    def __init__(self, count: int) -> None:
        self._available = list(range(1, count + 1))
        self._lock = threading.Lock()

    def acquire(self) -> int:
        with self._lock:
            return self._available.pop(0)

    def release(self, position: int) -> None:
        with self._lock:
            self._available.append(position)
            self._available.sort()


class StudyRunner:
    def __init__(self, config: StudyRunConfig) -> None:
        self.config = config
        self.experiment = config.experiment
        self.root = config.output_dir.resolve()
        self.seed_root = config.seed_run_dir.resolve()
        self.paraphrase_root = config.paraphrase_run_dir.resolve()
        self._manifest_lock = threading.Lock()

    def run(self) -> int:
        assignments = sorted(
            self.experiment.assignments,
            key=lambda item: int(item["execution_order"]),
        )
        paraphrase_validation.validate_paraphrase_run(
            self.paraphrase_root,
            self.experiment,
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
        manifest = self._start_manifest(assignments, existed)
        pending = self._pending_assignments(manifest, assignments)
        self._mark_study_running(manifest)
        if not pending:
            return self._finish_study(manifest)

        positions = _ProgressPositions(self.config.max_concurrency)
        with TerminalProgress(
            total=len(assignments),
            description="randomized study",
            unit="assignment",
            position=0,
        ) as progress:
            for _ in range(len(assignments) - len(pending)):
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = [
                    pool.submit(self._execute_assignment, assignment, positions)
                    for assignment in pending
                ]
                for future in as_completed(futures):
                    future.result()
                    progress.update()
        return self._finish_study(self._load_manifest())

    def _start_manifest(
        self,
        assignments: list[dict[str, object]],
        existed: bool,
    ) -> dict[str, object]:
        if not existed:
            manifest = self._new_manifest(assignments)
            self._write_manifest(manifest)
            return manifest
        manifest = self._load_manifest()
        self._validate_manifest_identity(manifest, assignments)
        _reclaim_interrupted_records(manifest)
        return manifest

    def _pending_assignments(
        self,
        manifest: dict[str, object],
        assignments: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return [
            assignment
            for assignment in assignments
            if _record_for(manifest, str(assignment["assignment_id"])).get("status")
            not in {"completed", "invalid"}
        ]

    def _mark_study_running(self, manifest: dict[str, object]) -> None:
        manifest["status"] = "running"
        manifest["finished_at"] = None
        manifest["max_concurrency_last_invocation"] = self.config.max_concurrency
        self._write_manifest(manifest)

    def _finish_study(self, manifest: dict[str, object]) -> int:
        statuses = {str(record["status"]) for record in _records(manifest)}
        manifest["status"] = "completed" if statuses == {"completed"} else "failed"
        manifest["finished_at"] = _now()
        self._write_manifest(manifest)
        _report_noncompleted_records(manifest)
        return int(manifest["status"] != "completed")

    def _execute_assignment(
        self,
        assignment: dict[str, object],
        positions: _ProgressPositions,
    ) -> None:
        position = positions.acquire()
        assignment_id = str(assignment["assignment_id"])
        try:
            self._mark_assignment_running(assignment_id)
            experiment_dir = self._experiment_dir(assignment)
            revision = self._revision_config(
                assignment,
                resume=os.path.lexists(experiment_dir),
            )
            run_submission_revision(
                replace(revision, progress_position=position),
                judgment_reuse_root=self.root / "shared-judgments",
            )
            study_validation.validate_completed_revision(
                experiment_dir,
                assignment,
                self.experiment,
                self.seed_root,
                self.paraphrase_root,
            )
            self._mark_assignment_completed(assignment_id)
        except (Exception, SystemExit) as exc:
            self._mark_assignment_failed(assignment_id, exc)
        finally:
            positions.release(position)

    def _mark_assignment_running(self, assignment_id: str) -> None:
        with self._manifest_lock:
            manifest = self._load_manifest()
            record = _record_for(manifest, assignment_id)
            record.update(
                {
                    "status": "running",
                    "started_at": _now(),
                    "finished_at": None,
                    "hostname": socket.gethostname(),
                    "pid": os.getpid(),
                    "attempt_count": int(record.get("attempt_count", 0)) + 1,
                }
            )
            for key in ("error_type", "error", "traceback"):
                record.pop(key, None)
            self._write_manifest(manifest)

    def _mark_assignment_completed(self, assignment_id: str) -> None:
        with self._manifest_lock:
            manifest = self._load_manifest()
            _record_for(manifest, assignment_id).update(
                {"status": "completed", "finished_at": _now()}
            )
            self._write_manifest(manifest)

    def _mark_assignment_failed(
        self,
        assignment_id: str,
        error: BaseException,
    ) -> None:
        with self._manifest_lock:
            manifest = self._load_manifest()
            _record_for(manifest, assignment_id).update(
                {
                    "status": "failed",
                    "finished_at": _now(),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                }
            )
            self._write_manifest(manifest)

    def _revision_config(
        self,
        assignment: dict[str, object],
        *,
        resume: bool,
    ) -> SubmissionRevisionConfig:
        protocol = self.experiment.protocol
        condition = self.experiment.condition(str(assignment["condition_id"]))
        feedback_policy = FeedbackPolicy(str(condition["feedback_policy"]))
        selection = paraphrase_validation.resolve_paraphrase_selection(
            self.paraphrase_root,
            self.experiment,
            str(assignment["task_id"]),
            int(assignment["replicate"]),
        )
        max_review_chars = protocol["max_review_chars"]
        if max_review_chars is not None and type(max_review_chars) is not int:
            raise RuntimeError("experiment max_review_chars is invalid")
        return SubmissionRevisionConfig(
            task_dir=self.experiment.task_dir(str(assignment["task_id"])),
            experiment_dir=self._experiment_dir(assignment),
            max_revisions=int(protocol["max_revisions"]),
            seed_run_dir=self.seed_root,
            agent=self.experiment.agent_config(
                quiet=True,
            ),
            experiment_id=self.experiment.experiment_id,
            assignment_id=str(assignment["assignment_id"]),
            condition_id=str(assignment["condition_id"]),
            replicate=int(assignment["replicate"]),
            elicitation_seed_replicates=self.experiment.replicates,
            execution_order=int(assignment["execution_order"]),
            optimizer_rubric_path=selection.optimizer_path,
            master_rubric_name=str(protocol["rubric_name"]),
            benchmark=self.experiment.benchmark,
            rubric_proposer_max_retries=int(protocol["rubric_proposer_max_retries"]),
            feedback_policy=feedback_policy,
            feedback_simulator=self.experiment.feedback_simulator_config(
                feedback_policy,
            ),
            prompt_profile=PromptProfile(str(protocol["prompt"])),
            rubric_policy=RubricPolicy(str(condition["rubric_policy"])),
            rubric_proposer_model=str(protocol["rubric_proposer_model"]),
            rubric_semantic_judge_model=str(protocol["rubric_semantic_judge_model"]),
            rubric_semantic_judge_max_calls=int(
                protocol["rubric_semantic_judge_max_calls_per_assignment"]
            ),
            rubric_semantic_judge_max_request_bytes=int(
                protocol["rubric_semantic_judge_max_request_bytes_per_call"]
            ),
            rubric_semantic_judge_max_output_tokens=int(
                protocol["rubric_semantic_judge_max_output_tokens_per_call"]
            ),
            review=str(protocol["review"]),
            judge_model=str(protocol["judge_model"]),
            max_review_chars=max_review_chars,
            resume=resume,
            show_progress=True,
        )

    def _experiment_dir(self, assignment: dict[str, object]) -> Path:
        return self.root / study_layout.study_experiment_relative_path(assignment)

    def _new_manifest(
        self,
        assignments: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "kind": STUDY_RUN_KIND,
            "status": "pending",
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "seed_run_dir": str(self.seed_root),
            "paraphrase_run_dir": str(self.paraphrase_root),
            "started_at": _now(),
            "finished_at": None,
            "max_concurrency_last_invocation": self.config.max_concurrency,
            "records": [self._new_record(item) for item in assignments],
        }

    def _new_record(self, assignment: dict[str, object]) -> dict[str, object]:
        return {
            "assignment_id": str(assignment["assignment_id"]),
            "task_id": str(assignment["task_id"]),
            "replicate": int(assignment["replicate"]),
            "condition_id": str(assignment["condition_id"]),
            "execution_order": int(assignment["execution_order"]),
            "experiment_dir": self._experiment_dir(assignment)
            .relative_to(self.root)
            .as_posix(),
            "status": "pending",
            "attempt_count": 0,
            "started_at": None,
            "finished_at": None,
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
        expected_identity = {
            "kind": STUDY_RUN_KIND,
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "seed_run_dir": str(self.seed_root),
            "paraphrase_run_dir": str(self.paraphrase_root),
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError("study resume identity differs from the experiment")
        records = _records(manifest)
        if [record.get("assignment_id") for record in records] != [
            item["assignment_id"] for item in assignments
        ]:
            raise RuntimeError("study assignment ledger differs from the experiment")
        for record, assignment in zip(records, assignments, strict=True):
            study_layout.resolve_study_experiment(self.root, record, assignment)


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


def _report_noncompleted_records(manifest: dict[str, object]) -> None:
    for record in _records(manifest):
        status = str(record.get("status"))
        if status == "completed":
            continue
        print(
            f"assignment {status}: {record.get('assignment_id')}: "
            f"{record.get('error_type')}: {record.get('error')}",
            file=sys.stderr,
        )


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
